#!/usr/bin/env python3
"""Behavioral evals for pol-devflow (manual; each real run spends LLM tokens).

For each scenario: build a tiny git fixture in a temporary directory, run the
configured agent command with cwd = that repo, store the transcript and check
deterministic expectations against the repo and the transcript.

Standard library only. Evaluation logic is pure (repo path + baseline +
transcript + expectations) so it can be unit-tested without any LLM.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
SCENARIOS_DIR = EVALS_DIR / 'scenarios'
MAIN = 'main'
DEFAULT_EXCLUDE = ['docs/devflow/']

# type -> (required params, optional params)
VOCABULARY = {
    'branch_created_prefix': ({'prefix'}, set()),
    'no_new_branches': (set(), set()),
    'branches_preserved': (set(), set()),
    'main_unchanged': (set(), set()),
    'no_new_commits': (set(), set()),
    'max_product_files_changed': ({'max'}, {'branch_prefix', 'exclude'}),
    'path_absent': ({'path'}, set()),
    'path_present': ({'path'}, {'on_branch_prefix'}),
    'worktree_clean': (set(), set()),
    'user_change_preserved': ({'path', 'content'}, set()),
    'command_passes': ({'command'}, {'on_branch_prefix', 'timeout'}),
    'transcript_contains_any': ({'patterns'}, set()),
    'no_remote_push': (set(), set()),
}
DANGEROUS_MARKERS = ('dangerously', 'bypasspermissions', 'bypass-approvals', 'skip-permissions')


# --------------------------------------------------------------------------- git helpers

def git(repo, *args, check=True):
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def branches(repo):
    out = git(repo, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads')
    return dict(line.rsplit(' ', 1) for line in out.splitlines() if line.strip())


def snapshot(repo):
    """State recorded right after the fixture is built; expectations compare against it."""
    return {
        'branches': branches(repo),
        'commits': sorted(git(repo, 'rev-list', '--all').split()),
        'status': git(repo, 'status', '--porcelain=v1', '-uall'),
        'remotes': sorted(git(repo, 'remote').split()),
    }


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode('utf-8'))


def _commit_all(repo, message):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)


def build_fixture(fixture, repo):
    """Create a committed repo on main (+ extra branches, + optional dirty change). Returns baseline."""
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=False)
    git(repo, 'init', '-q')
    git(repo, 'symbolic-ref', 'HEAD', f'refs/heads/{MAIN}')
    for key, value in (('user.name', 'DevFlow Eval'), ('user.email', 'eval@example.invalid'),
                       ('commit.gpgsign', 'false'), ('core.autocrlf', 'false')):
        git(repo, 'config', key, value)
    for name, content in fixture['files'].items():
        _write(repo / name, content)
    _commit_all(repo, 'fixture: initial')
    for extra in fixture.get('extra_branches', []):
        git(repo, 'checkout', '-q', '-b', extra['name'])
        for name, content in extra.get('files', {}).items():
            _write(repo / name, content)
        _commit_all(repo, f"fixture: {extra['name']}")
        git(repo, 'checkout', '-q', MAIN)
        if extra.get('merge'):
            git(repo, 'merge', '-q', '--ff-only', extra['name'])
    for name, content in fixture.get('dirty', {}).items():
        _write(repo / name, content)
    return snapshot(repo)


# --------------------------------------------------------------------------- scenarios

def validate_scenario(data):
    errors = []
    for key in ('id', 'description', 'prompt', 'fixture', 'expectations'):
        if key not in data:
            errors.append(f'missing key: {key}')
    if errors:
        return errors
    fixture = data['fixture']
    if not isinstance(fixture.get('files'), dict) or not fixture['files']:
        errors.append('fixture.files must be a non-empty object')
    for extra in fixture.get('extra_branches', []):
        if 'name' not in extra:
            errors.append('extra_branches entries need a name')
    if not isinstance(fixture.get('dirty', {}), dict):
        errors.append('fixture.dirty must be an object')
    if not isinstance(data['expectations'], list) or not data['expectations']:
        errors.append('expectations must be a non-empty list')
        return errors
    for i, exp in enumerate(data['expectations']):
        kind = exp.get('type')
        if kind not in VOCABULARY:
            errors.append(f'expectation {i}: unknown type {kind!r}')
            continue
        required, optional = VOCABULARY[kind]
        params = set(exp) - {'type'}
        if required - params:
            errors.append(f'expectation {i} ({kind}): missing {sorted(required - params)}')
        if params - required - optional:
            errors.append(f'expectation {i} ({kind}): unknown params {sorted(params - required - optional)}')
        if kind == 'command_passes' and not (isinstance(exp.get('command'), list) and exp['command']):
            errors.append(f'expectation {i} (command_passes): command must be a non-empty argv list')
        if kind == 'transcript_contains_any' and not (isinstance(exp.get('patterns'), list) and exp['patterns']):
            errors.append(f'expectation {i} (transcript_contains_any): patterns must be a non-empty list')
    return errors


def load_scenarios(directory=SCENARIOS_DIR, only=None):
    scenarios = []
    for path in sorted(Path(directory).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        errors = validate_scenario(data)
        if errors:
            raise ValueError(f'{path.name}: ' + '; '.join(errors))
        scenarios.append(data)
    ids = [s['id'] for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate scenario ids')
    if only:
        unknown = set(only) - set(ids)
        if unknown:
            raise ValueError(f'unknown scenario ids: {sorted(unknown)}')
        scenarios = [s for s in scenarios if s['id'] in only]
    return scenarios


# --------------------------------------------------------------------------- expectations

def _matches(name, path):
    base = path.rstrip('/')
    return name == base or name.startswith(base + '/')


def _tree(repo, ref):
    return git(repo, 'ls-tree', '-r', '--name-only', ref).splitlines()


def _new_branches(repo, baseline, prefix=None):
    return sorted(name for name in branches(repo)
                  if name not in baseline['branches'] and (prefix is None or name.startswith(prefix)))


def _run_on_branch(repo, branch, command, timeout):
    """Export the branch tree with git archive (repo untouched) and run the command there."""
    archive = subprocess.run(['git', 'archive', '--format=tar', branch], cwd=repo, capture_output=True,
                             stdin=subprocess.DEVNULL)
    if archive.returncode != 0:
        return False, archive.stderr.decode('utf-8', 'replace')
    with tempfile.TemporaryDirectory(prefix='devflow-eval-cmd-', ignore_cleanup_errors=True) as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            if hasattr(tarfile, 'data_filter'):
                tar.extractall(tmp, filter='data')
            else:
                tar.extractall(tmp)
        return _run(command, tmp, timeout)


def _run(command, cwd, timeout):
    argv = [sys.executable if token == '{python}' else token for token in command]
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
    return result.returncode == 0, f"exit {result.returncode}: {' | '.join(tail)}"


def check_expectation(repo, baseline, transcript, exp):
    """Return (passed, detail) for one expectation."""
    repo = Path(repo)
    kind = exp['type']
    if kind == 'branch_created_prefix':
        found = _new_branches(repo, baseline, exp['prefix'])
        return bool(found), f'new branches: {found or _new_branches(repo, baseline)}'
    if kind == 'no_new_branches':
        found = _new_branches(repo, baseline)
        return not found, f'new branches: {found}'
    if kind == 'branches_preserved':
        current = branches(repo)
        changed = sorted(n for n, sha in baseline['branches'].items() if current.get(n) != sha)
        return not changed, f'missing or moved: {changed}'
    if kind == 'main_unchanged':
        now = branches(repo).get(MAIN)
        return now == baseline['branches'][MAIN], f'{MAIN}: {baseline["branches"][MAIN][:8]} -> {(now or "deleted")[:8]}'
    if kind == 'no_new_commits':
        new = sorted(set(git(repo, 'rev-list', '--all').split()) - set(baseline['commits']))
        return not new, f'{len(new)} new commit(s)'
    if kind == 'max_product_files_changed':
        exclude = exp.get('exclude', DEFAULT_EXCLUDE)
        counts = {}
        for name in _new_branches(repo, baseline, exp.get('branch_prefix')):
            base = git(repo, 'merge-base', baseline['branches'][MAIN], name).strip()
            files = [f for f in git(repo, 'diff', '--name-only', base, name).splitlines()
                     if f and not any(_matches(f, e) for e in exclude)]
            counts[name] = files
        over = {n: f for n, f in counts.items() if len(f) > exp['max']}
        detail = {n: len(f) for n, f in counts.items()} or 'no new branches'
        return not over, f'product files per branch: {detail} (max {exp["max"]})'
    if kind == 'path_absent':
        hits = ['worktree'] if (repo / exp['path']).exists() else []
        hits += [ref for ref in branches(repo) if any(_matches(n, exp['path']) for n in _tree(repo, ref))]
        return not hits, f'found in: {hits}' if hits else 'absent everywhere'
    if kind == 'path_present':
        prefix = exp.get('on_branch_prefix')
        if prefix is None:
            return (repo / exp['path']).exists(), 'checked worktree'
        refs = _new_branches(repo, baseline, prefix)
        hits = [ref for ref in refs if any(_matches(n, exp['path']) for n in _tree(repo, ref))]
        return bool(hits), f'present in: {hits} (candidates {refs})'
    if kind == 'worktree_clean':
        status = git(repo, 'status', '--porcelain=v1', '-uall').strip()
        return not status, f'status: {status.splitlines()[:5]}' if status else 'clean'
    if kind == 'user_change_preserved':
        target = repo / exp['path']
        if not target.is_file():
            return False, 'file missing'
        same = target.read_bytes().decode('utf-8', 'replace').replace('\r\n', '\n') == exp['content']
        return same, 'content preserved' if same else 'content differs'
    if kind == 'command_passes':
        timeout = exp.get('timeout', 120)
        prefix = exp.get('on_branch_prefix')
        if prefix is None:
            return _run(exp['command'], repo, timeout)
        refs = _new_branches(repo, baseline, prefix)
        if not refs:
            return False, f'no new branch with prefix {prefix}'
        ok, detail = _run_on_branch(repo, refs[-1], exp['command'], timeout)
        return ok, f'{refs[-1]}: {detail}'
    if kind == 'transcript_contains_any':
        text = transcript.lower()
        hits = [p for p in exp['patterns'] if p.lower() in text]
        return bool(hits), f'matched: {hits}' if hits else f'none of {exp["patterns"]}'
    if kind == 'no_remote_push':
        remotes = sorted(git(repo, 'remote').split())
        return remotes == baseline['remotes'], f'remotes: {remotes}'
    raise ValueError(f'unknown expectation type {kind!r}')


def evaluate(repo, baseline, transcript, expectations):
    results = []
    for exp in expectations:
        try:
            ok, detail = check_expectation(repo, baseline, transcript, exp)
        except Exception as exc:  # report, do not abort the rest
            ok, detail = False, f'error: {exc}'
        results.append({'type': exp['type'], 'passed': bool(ok), 'detail': str(detail), 'expectation': exp})
    return results


# --------------------------------------------------------------------------- agent command

def _is_dangerous(argv):
    return any(marker in token.lower().replace('_', '') for token in argv for marker in DANGEROUS_MARKERS)


def build_command(args, prompt, repo):
    """Return argv for the agent. Raises ValueError on unsafe configuration."""
    if args.runner_cmd:
        template = args.runner_cmd.strip()
        tokens = json.loads(template) if template.startswith('[') else shlex.split(template)
        argv = [t.replace('{prompt}', prompt).replace('{repo}', str(repo)) for t in tokens]
        if _is_dangerous(tokens) and not args.allow_skip_permissions:
            raise ValueError('runner-cmd contains a permission-bypass flag; pass --allow-skip-permissions to allow it')
        return argv
    if args.runner == 'claude':
        if args.permission_mode == 'bypassPermissions' and not args.allow_skip_permissions:
            raise ValueError('--permission-mode bypassPermissions requires --allow-skip-permissions')
        argv = ['claude', '-p', prompt, '--output-format', 'text', '--permission-mode', args.permission_mode]
        if args.allowed_tools:
            argv += ['--allowedTools', args.allowed_tools]
        if args.model:
            argv += ['--model', args.model]
        if args.allow_skip_permissions:
            argv.append('--dangerously-skip-permissions')
        return argv
    if args.runner == 'codex':
        # Best-effort template: Codex invokes skills with $name instead of /name.
        codex_prompt = '$' + prompt[1:] if prompt.startswith('/pol-devflow') else prompt
        argv = ['codex', 'exec', '--cd', str(repo)]
        argv += ['--dangerously-bypass-approvals-and-sandbox'] if args.allow_skip_permissions else ['--sandbox', 'workspace-write']
        if args.model:
            argv += ['--model', args.model]
        return argv + [codex_prompt]
    raise ValueError(f'unknown runner {args.runner!r}')


def _resolve(argv):
    found = shutil.which(argv[0])
    return [found, *argv[1:]] if found else argv


def run_agent(argv, repo, env, timeout):
    start = time.monotonic()
    try:
        result = subprocess.run(_resolve(argv), cwd=repo, env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout, stdin=subprocess.DEVNULL)
        outcome, out, err, code = 'ok', result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        def text(value):
            return value.decode('utf-8', 'replace') if isinstance(value, bytes) else (value or '')
        outcome, out, err, code = 'timeout', text(exc.stdout), text(exc.stderr), None
    except OSError as exc:
        outcome, out, err, code = 'error', '', f'could not start agent: {exc}', None
    return {'outcome': outcome, 'exit_code': code, 'stdout': out, 'stderr': err,
            'seconds': round(time.monotonic() - start, 1)}


# --------------------------------------------------------------------------- CLI

def _rmtree(path):
    def retry(func, target, _):  # git marks object files read-only on Windows
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if Path(path).exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=retry)
        else:
            shutil.rmtree(path, onerror=retry)


def _inside_git_worktree(path):
    result = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=path, capture_output=True,
                            text=True, stdin=subprocess.DEVNULL)
    return result.returncode == 0 and result.stdout.strip() == 'true'


def parse_args(argv=None):
    p = argparse.ArgumentParser(description='Run pol-devflow behavioral evals (each real run spends LLM tokens).')
    p.add_argument('--runner', choices=('claude', 'codex'), default='claude')
    p.add_argument('--runner-cmd', help='custom command template with {prompt} (and optional {repo}); '
                                        'shell-like string or JSON list')
    p.add_argument('--permission-mode', default='acceptEdits', help='claude --permission-mode (default acceptEdits)')
    p.add_argument('--allowed-tools', default='Bash(git:*) Bash(python:*) Bash(python3:*) Bash(py:*)',
                   help='claude --allowedTools value ("" to omit)')
    p.add_argument('--model', help='model passed to the runner')
    p.add_argument('--allow-skip-permissions', action='store_true',
                   help='DANGEROUS: add the runner permission-bypass flag (only inside the temp fixture)')
    p.add_argument('--scenario', action='append', default=[], help='scenario id (repeatable); default all')
    p.add_argument('--list', action='store_true', help='list scenarios and exit')
    p.add_argument('--dry-run', action='store_true', help='build fixtures and print commands; never run the agent')
    p.add_argument('--keep', action='store_true', help='keep fixture repos after the run')
    p.add_argument('--timeout', type=int, default=900, help='seconds per scenario (default 900)')
    p.add_argument('--out', help='output directory (default: new temp dir); must not be inside a git repo')
    return p.parse_args(argv)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # prompts contain non-ASCII; avoid cp1252 crashes on Windows
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    args = parse_args(argv)
    scenarios = load_scenarios(only=args.scenario or None)
    if args.list:
        for s in scenarios:
            print(f"{s['id']:<28} {s['description']}")
        return 0
    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        out = Path(tempfile.mkdtemp(prefix='pol-devflow-evals-')).resolve()
    if _inside_git_worktree(out):
        print(f'refusing to run: {out} is inside a git work tree; use a temp directory', file=sys.stderr)
        return 2
    if args.allow_skip_permissions and not args.dry_run:
        print('WARNING: --allow-skip-permissions given; the agent will run WITHOUT permission prompts '
              '(cwd is the temp fixture, but the process still has your user rights).', file=sys.stderr)
    if not args.dry_run:
        print(f'Running {len(scenarios)} scenario(s) with a real agent: this spends tokens.', file=sys.stderr)

    rows = []
    for scenario in scenarios:
        sid = scenario['id']
        workdir = out / sid
        if workdir.exists():
            _rmtree(workdir)
        workdir.mkdir(parents=True)
        repo = workdir / 'repo'
        baseline = build_fixture(scenario['fixture'], repo)
        (workdir / 'baseline.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
        try:
            command = build_command(args, scenario['prompt'], repo)
        except ValueError as exc:
            print(f'error: {exc}', file=sys.stderr)
            return 2
        if args.dry_run:
            print(f'[{sid}] cwd={repo}')
            print(f'[{sid}] ' + ' '.join(shlex.quote(t) for t in command))
            rows.append({'id': sid, 'status': 'DRY', 'command': command})
            if not args.keep:
                _rmtree(repo)
            continue
        env = dict(os.environ, DEVFLOW_DATA_HOME=str(workdir / 'devflow-data'))
        run = run_agent(command, repo, env, args.timeout)
        transcript = run['stdout'] + '\n--- STDERR ---\n' + run['stderr']
        (workdir / 'transcript.txt').write_text(transcript, encoding='utf-8')
        checks = evaluate(repo, baseline, transcript, scenario['expectations'])
        passed = sum(c['passed'] for c in checks)
        status = 'ERROR' if run['outcome'] != 'ok' else ('PASS' if passed == len(checks) else 'FAIL')
        rows.append({'id': sid, 'status': status, 'agent': {k: v for k, v in run.items() if k not in ('stdout', 'stderr')},
                     'passed': passed, 'total': len(checks), 'checks': checks, 'command': command,
                     'transcript': str(workdir / 'transcript.txt')})
        if not args.keep:
            _rmtree(repo)
            _rmtree(workdir / 'devflow-data')

    results = {'created_at': datetime.now(timezone.utc).isoformat(), 'runner': args.runner_cmd or args.runner,
               'dry_run': args.dry_run, 'out': str(out), 'scenarios': rows}
    (out / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print()
    print(f"{'scenario':<28} {'status':<6} {'checks':>7} {'secs':>7}")
    for row in rows:
        checks = f"{row['passed']}/{row['total']}" if 'total' in row else '-'
        secs = row.get('agent', {}).get('seconds', '-')
        print(f"{row['id']:<28} {row['status']:<6} {checks:>7} {secs:>7}")
        for c in row.get('checks', []):
            if not c['passed']:
                print(f"    FAIL {c['type']}: {c['detail']}")
        if row.get('agent', {}).get('outcome') in ('error', 'timeout'):
            print(f"    agent {row['agent']['outcome']} (see {row['transcript']})")
    print(f'\nresults: {out / "results.json"}')
    return 0 if all(r['status'] in ('PASS', 'DRY') for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
