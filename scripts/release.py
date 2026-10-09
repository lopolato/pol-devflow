#!/usr/bin/env python3
"""Release pol-devflow from main: checks, tests, tag and optional push/install.

Usage: python scripts/release.py VERSION [--push] [--install] [--skip-tests] [--skip-ci-check]
                                 [--evals [--yes]] [--dry-run]

main is protected: the version bump, the VERIFICATION.md section and the README heading arrive
through a feature branch with green CI. This script never edits files or commits; it creates the tag.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = Path(__file__).resolve().parents[1]
INIT = 'scripts/devflow/__init__.py'
VERSION_RE = re.compile(r"""__version__\s*=\s*(['"])([^'"]+)\1""")
EVALS_WARNING = ('WARNING: --evals launches real LLM sessions (claude) and spends tokens: '
                 'evals/check_claude_nesting.py and evals/run_evals.py --scenario lite-small-bug. '
                 'They evaluate the installed skill, not this checkout.')


class ReleaseError(Exception):
    pass


def parse_version(text):
    if not re.fullmatch(r'\d+(\.\d+)*', text or ''):
        raise ReleaseError(f'Invalid version {text!r}: expected dotted integers such as 1.0.17')
    parts = [int(p) for p in text.split('.')]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def github_slug(url):
    """owner/repo for a github.com origin URL; None for local paths or other hosts."""
    match = re.fullmatch(r'(?:https?://(?:[^@/]+@)?github\.com/|(?:ssh://)?git@github\.com[:/])'
                         r'([\w.-]+)/([\w.-]+?)(?:\.git)?/?', url.strip())
    return f'{match.group(1)}/{match.group(2)}' if match else None


def summarize_check_runs(payload):
    """('success'|'pending'|'failure'|'missing', detail) from a GitHub check-runs response."""
    runs = payload.get('check_runs') or []
    if not runs:
        return 'missing', 'no check runs reported for this commit'
    pending = [r.get('name', '?') for r in runs if r.get('status') != 'completed']
    failed = [f"{r.get('name', '?')}={r.get('conclusion')}" for r in runs
              if r.get('status') == 'completed' and r.get('conclusion') not in ('success', 'neutral', 'skipped')]
    if failed:
        return 'failure', ', '.join(failed)
    if pending:
        return 'pending', 'still running: ' + ', '.join(pending)
    return 'success', f'{len(runs)} check run(s) passed'


def gh_check_runs(slug, sha):
    """Check runs of sha via gh; None when gh is missing or not authenticated."""
    if not shutil.which('gh'):
        return None
    if subprocess.run(['gh', 'auth', 'status'], capture_output=True).returncode:
        return None
    result = subprocess.run(['gh', 'api', f'repos/{slug}/commits/{sha}/check-runs?per_page=100'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ReleaseError('gh api failed: ' + (result.stderr or result.stdout).strip())
    return summarize_check_runs(json.loads(result.stdout))


class Release:
    def __init__(self, args, ci_runner=gh_check_runs):
        self.args = args
        self.repo = Path(args.repo).resolve()
        self.version = args.version
        self.tag = 'v' + args.version
        self.dry = args.dry_run
        self.py = sys.executable
        self.ci_runner = ci_runner

    # -- helpers -------------------------------------------------------
    def say(self, text):
        print(text, flush=True)

    def git(self, *args, check=True):
        result = subprocess.run(['git', *args], cwd=self.repo, capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        if check and result.returncode:
            raise ReleaseError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
        return result

    def run(self, command, label):
        """Run a command, or only print it in dry-run."""
        shown = ' '.join(f'"{c}"' if ' ' in c else c for c in command)
        self.say(('[dry-run] ' if self.dry else '$ ') + shown)
        if self.dry:
            return
        # No bytecode: __pycache__ left by the test run would make the tree look dirty afterwards.
        result = subprocess.run(command, cwd=self.repo, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if result.returncode:
            raise ReleaseError(f'{label} failed (exit {result.returncode})')

    # -- steps ---------------------------------------------------------
    def preflight(self):
        self.say(f'== 1. Preflight for {self.tag} in {self.repo}')
        target = parse_version(self.version)
        top = self.git('rev-parse', '--show-toplevel', check=False)
        if top.returncode or Path(top.stdout.strip()).resolve() != self.repo:
            raise ReleaseError(f'{self.repo} is not the root of a Git repository')
        branch = self.git('rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
        if branch != 'main':
            raise ReleaseError(f'Releases are made from main; current branch is {branch}')
        dirty = self.git('status', '--porcelain', '--untracked-files=all').stdout.strip()
        if dirty:
            raise ReleaseError('Working tree is not clean; commit or stash first:\n' + dirty)
        origin = self.git('config', '--get', 'remote.origin.url', check=False)
        if origin.returncode or not origin.stdout.strip():
            raise ReleaseError('Remote origin is not configured')
        self.origin_url = origin.stdout.strip()
        if self.dry:
            self.say('[dry-run] git fetch origin (skipped; comparing with the last fetched origin/main)')
        else:
            self.say('$ git fetch origin')
            self.git('fetch', 'origin')
        if self.git('rev-parse', '--verify', '-q', 'refs/remotes/origin/main', check=False).returncode:
            raise ReleaseError('origin/main not found; fetch it first')
        if self.git('merge-base', '--is-ancestor', 'origin/main', 'HEAD', check=False).returncode:
            raise ReleaseError('main is behind or has diverged from origin/main; update it first')
        ahead = int(self.git('rev-list', '--count', 'origin/main..HEAD').stdout.strip())
        self.say(f'main is up to date with origin/main ({ahead} local commit(s) ahead)')
        self.sha = self.git('rev-parse', 'HEAD').stdout.strip()

        init = self.repo / INIT
        match = VERSION_RE.search(init.read_text(encoding='utf-8')) if init.is_file() else None
        if not match:
            raise ReleaseError(f'__version__ not found in {INIT}')
        if match.group(2) != self.version:
            raise ReleaseError(f'{INIT} declares {match.group(2)}, not {self.version}. Bump it (with VERIFICATION.md '
                               'and the README heading) in the feature branch, let CI pass and fast-forward main; '
                               'this script never commits on main')
        tags = [t[1:] for t in self.git('tag', '--list', 'v*').stdout.split() if re.fullmatch(r'v\d+(\.\d+)*', t)]
        if self.version in tags:
            raise ReleaseError(f'Tag {self.tag} already exists')
        if self.git('ls-remote', '--tags', 'origin', f'refs/tags/{self.tag}', check=False).stdout.strip():
            raise ReleaseError(f'Tag {self.tag} already exists in origin')
        newer = [t for t in tags if parse_version(t) >= target]
        if newer:
            raise ReleaseError(f'Version {self.version} is not greater than the current '
                               f'v{max(newer, key=parse_version)}')

        verification = self.repo / 'VERIFICATION.md'
        text = verification.read_text(encoding='utf-8') if verification.is_file() else ''
        if not re.search(rf'(?m)^## {re.escape(self.version)}(?=[ \t\r]|$)', text):
            raise ReleaseError(f'VERIFICATION.md needs a "## {self.version}" section with the release evidence')
        readme = self.repo / 'README.md'
        lines = readme.read_text(encoding='utf-8').splitlines() if readme.is_file() else []
        heading = next((line.strip() for line in lines if line.startswith('# ')), None)
        if heading != f'# Pol DevFlow {self.version}':
            raise ReleaseError(f'README.md first heading must be "# Pol DevFlow {self.version}" (found {heading!r})')
        previous = f'v{max(tags, key=parse_version)}' if tags else 'no previous tag'
        self.say(f'{INIT}, VERIFICATION.md and README.md declare {self.version} ({previous} -> {self.tag})')

        if self.args.evals:
            self.say(EVALS_WARNING)
            if not self.dry and not self.args.yes:
                try:  # NUL is a tty on Windows: EOF also means non-interactive
                    if not (sys.stdin and sys.stdin.isatty()):
                        raise EOFError
                    answer = input('Run the evals now? [y/N] ')
                except EOFError:
                    raise ReleaseError('--evals needs --yes when not running interactively') from None
                if answer.strip().lower() not in ('y', 'yes', 's', 'si'):
                    raise ReleaseError('Evals not confirmed; nothing was changed')

    def ci_check(self):
        self.say(f'== 2. CI checks of {self.sha[:12]} on GitHub')
        if self.args.skip_ci_check:
            self.say('WARNING: --skip-ci-check: GitHub check runs were not verified.')
            return
        slug = github_slug(self.origin_url)
        if not slug:
            self.say('origin is not a GitHub repository; CI check skipped')
            return
        status = self.ci_runner(slug, self.sha)
        if status is None:
            self.say('WARNING: gh is not available or not authenticated; CI check skipped (verify it on GitHub)')
            return
        state, detail = status
        if state != 'success':
            raise ReleaseError(f'CI checks of {self.sha[:12]} are {state}: {detail}. '
                               'Wait for green checks or pass --skip-ci-check')
        self.say(f'CI checks: success ({detail})')

    def tests(self):
        self.say('== 3. Tests and package validation')
        if self.args.skip_tests:
            self.say('WARNING: --skip-tests: tests were not run here; the CI checks on main must be green.')
            return
        self.run([self.py, '-m', 'unittest', 'discover', '-s', 'tests'], 'Unit tests')
        self.run([self.py, 'scripts/validate.py'], 'Package validation')

    def evals(self):
        if not self.args.evals:
            return
        self.say('== 4. Behaviour evals (spend tokens)')
        self.run([self.py, 'evals/check_claude_nesting.py'], 'Claude nesting check')
        self.run([self.py, 'evals/run_evals.py', '--scenario', 'lite-small-bug'], 'Eval lite-small-bug')

    def tag_release(self):
        self.say(f'== 5. Tag {self.tag} on main ({self.sha[:12]}); no commit is created')
        self.run(['git', 'tag', '-a', self.tag, '-m', f'Pol DevFlow {self.version}', self.sha], 'git tag')

    def publish(self):
        if self.args.push:
            self.say('== 6. Push main and tag')
            self.run(['git', 'push', '--atomic', 'origin', 'refs/heads/main', f'refs/tags/{self.tag}'], 'git push')
        if self.args.install:
            self.say('== 6. Install in the local runtimes and validate them')
            self.run([self.py, 'scripts/install.py', '--runtime', 'all'], 'Install')
            self.run([self.py, 'scripts/validate.py', '--runtime', 'claude'], 'Claude installation validation')
            self.run([self.py, 'scripts/validate.py', '--runtime', 'codex'], 'Codex installation validation')

    def execute(self):
        self.preflight()
        self.ci_check()
        self.tests()
        self.evals()
        self.tag_release()
        self.publish()
        if self.dry:
            self.say('Dry run finished: nothing was changed.')
        elif self.args.push:
            self.say(f'Released {self.tag} (pushed).')
        else:
            self.say(f'Released {self.tag} locally; publish with: git push --atomic origin main {self.tag}')


def build_parser():
    parser = argparse.ArgumentParser(description='Release pol-devflow from a clean, up-to-date main.')
    parser.add_argument('version', help='version to tag, e.g. 1.0.17 (already declared on main)')
    parser.add_argument('--push', action='store_true', help='push main and the tag to origin')
    parser.add_argument('--install', action='store_true', help='install in the local runtimes and validate them')
    parser.add_argument('--skip-tests', action='store_true', help='do not run the tests locally (CI must be green)')
    parser.add_argument('--skip-ci-check', action='store_true', help='do not verify GitHub check runs of HEAD')
    parser.add_argument('--evals', action='store_true', help='also run the paid behaviour evals (asks first)')
    parser.add_argument('--yes', action='store_true', help='confirm --evals without asking')
    parser.add_argument('--dry-run', action='store_true', help='print every step without changing anything')
    parser.add_argument('--repo', default=str(DEFAULT_REPO), help=argparse.SUPPRESS)
    return parser


def main(argv=None, ci_runner=gh_check_runs):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    args = build_parser().parse_args(argv)
    try:
        Release(args, ci_runner).execute()
    except ReleaseError as error:
        print(f'release: error: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('release: interrupted', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
