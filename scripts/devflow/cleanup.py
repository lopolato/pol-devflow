"""Owned cleanup: list first; remove only recorded, merged and clean DevFlow branches/worktrees."""
import os
import json
import shutil
import subprocess
from pathlib import Path
from . import gitops, state
from .storage import DevFlowError, FileLock, atomic_write, digest, inside, json_bytes, now, read_json, safe_id

PROTECTED = ('main', 'master')
HISTORY = 'history retained; use --purge-history to explicitly remove it'


def register_workspace(data, repository, value):
    """Explicit Coordinator provenance for an existing Orca-created task checkout."""
    repo = gitops.inspect(repository)['workspace']
    if not isinstance(value, dict) or value.get('backend') != 'orca':
        raise DevFlowError('Workspace registration requires backend orca')
    for key in ('workspace', 'branch', 'worktree_id', 'evidence'):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise DevFlowError('Workspace registration needs ' + key)
    workspace = str(Path(value['workspace']).resolve())
    if Path(data).resolve().is_relative_to(Path(repo).resolve()):
        raise DevFlowError('Ownership records must stay outside the source repository')
    trees = _worktrees(repo)
    primary = next(iter(trees))
    if _norm(workspace) == primary or _norm(workspace) not in trees:
        raise DevFlowError('Only an existing secondary Git worktree can be registered')
    if value['branch'] in PROTECTED or trees[_norm(workspace)] != value['branch']:
        raise DevFlowError('Registration needs the current unprotected task branch')
    command = value.get('orca_command', 'orca')
    if not isinstance(command, str) or Path(command).stem not in ('orca', 'orca-dev', 'orca-ide'):
        raise DevFlowError('Use the resolved Orca executable, without shell arguments')
    record = {'schema_version': 1, 'kind': 'root', 'backend': 'orca',
              'repository': repo, 'git_common_dir': gitops.common_dir(repo),
              'workspace': workspace, 'branch': value['branch'],
              'worktree_id': value['worktree_id'], 'orca_command': command,
              'evidence': value['evidence'], 'created_at': now()}
    path = Path(data) / 'worktrees/.devflow-ownership' / (digest(_norm(workspace).encode())[:24] + '.json')
    for other in path.parent.glob('*.json'):
        if other != path and _norm(read_json(other).get('workspace', '')) == _norm(workspace):
            raise DevFlowError('Workspace already has another ownership record; reconcile instead of claiming it')
    with FileLock(path.with_suffix('.lock'), 'workspace-register'):
        if path.exists():
            old = read_json(path)
            if any(old.get(k) != record.get(k) for k in ('workspace', 'branch', 'backend', 'worktree_id')) or old.get('removed_at'):
                raise DevFlowError('Conflicting workspace ownership; inspect existing record')
            return old
        atomic_write(path, json_bytes(record))
    return record


def _orca_workspace(record, action):
    command = record.get('orca_command', 'orca')
    if not isinstance(command, str) or Path(command).stem not in ('orca', 'orca-dev', 'orca-ide'):
        raise DevFlowError('Invalid recorded Orca executable')
    args = [command, 'worktree', 'rm' if action == 'remove' else 'show',
            '--worktree', 'id:' + record['worktree_id'], '--json']
    try:
        process = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', timeout=180)
        value = json.loads(process.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise DevFlowError('Orca operation did not return verified evidence: ' + str(exc)) from exc
    if not value.get('ok'):
        if action != 'remove' and value.get('error', {}).get('code') == 'selector_not_found':
            return {'exists': False}
        raise DevFlowError('Orca workspace operation failed: ' + str(value.get('error', {})))
    if action != 'remove':
        observed = value.get('result', {}).get('worktree', {})
        if _norm(observed.get('path', '')) != _norm(record['workspace']):
            raise DevFlowError('Orca workspace identity no longer matches the owned path')
    return {'exists': action != 'remove'}


def _norm(path):
    value = str(Path(path).resolve())
    return value.lower() if os.name == 'nt' else value


def _worktrees(repo):
    """Registered worktrees of this repository: normalized path -> checked-out branch."""
    result, current = {}, None
    for line in gitops.git(repo, 'worktree', 'list', '--porcelain').splitlines():
        if line.startswith('worktree '):
            current = _norm(line[len('worktree '):])
            result[current] = None
        elif line.startswith('branch ') and current:
            result[current] = line[len('branch '):].removeprefix('refs/heads/')
    return result


def _branch_sha(repo, branch):
    try:
        return gitops.git(repo, 'rev-parse', '--verify', '--quiet', 'refs/heads/' + branch)
    except DevFlowError:
        return None


def target_branch(repo, into=None):
    if into:
        gitops.git(repo, 'rev-parse', '--verify', into + '^{commit}')
        return into
    for name in PROTECTED:
        if _branch_sha(repo, name):
            return name
    raise DevFlowError('No main/master branch; pass --into REF')


def _records(data, paths, common):
    """Collect DevFlow-owned branches of this repository from lite records, runs and worktree ownership."""
    data, items, known = Path(data), {}, {}

    def ours(repository, recorded_common=None):
        # Main checkout and linked worktrees share one Git common dir; the data dir is shared by all repositories.
        if repository and _norm(repository) in paths:
            return True
        if recorded_common:
            return _norm(recorded_common) == common
        if not repository:
            return False
        if repository not in known:
            try:
                known[repository] = _norm(gitops.common_dir(repository)) == common
            except DevFlowError:
                known[repository] = False
        return known[repository]

    def entry(branch):
        return items.setdefault(branch, {'branch': branch, 'worktrees': [], 'runs': [], 'lite_records': [],
                                         'ownership_records': []})

    for path in sorted((data / 'lite').glob('*.json')) if (data / 'lite').is_dir() else []:
        record = read_json(path)
        if record.get('kind') == 'lite' and record.get('branch') and ours(record.get('repository'),
                                                                          record.get('git_common_dir')):
            entry(record['branch'])['lite_records'].append(str(path))
            binding = record.get('orca') or {}
            if record.get('executor') == 'orca' and (not binding.get('settlement') or not binding.get('accounting')):
                entry(record['branch'])['orca_lite_unsettled'] = True
    for path in sorted((data / 'runs').glob('*/state.json')) if (data / 'runs').is_dir() else []:
        try:
            run = state.load(data, path.parent.name)
        except DevFlowError:
            continue
        if run.get('branch') and ours(run['repository'], run.get('git_common_dir')):
            item = entry(run['branch'])
            unsettled = run.get('executor') == 'orca' and any(
                not t.get('orca', {}).get('settlement') or not t.get('orca', {}).get('accounting')
                for t in run['tasks'])
            item['runs'].append({'run_id': run['run_id'],
                                 'status': 'orca_unsettled' if unsettled else run['status'], 'dir': str(path.parent)})
    owners = data / 'worktrees' / '.devflow-ownership'
    for path in sorted(owners.glob('*.json')) if owners.is_dir() else []:
        record = read_json(path)
        if record.get('removed_at') or not record.get('branch'):
            continue
        workspace = record.get('workspace', '')
        if not workspace:
            continue
        # Legacy records without repository identity only match a worktree Git still lists for this repository.
        identified = record.get('repository') or record.get('git_common_dir')
        if _norm(workspace) in paths or (identified and Path(workspace).exists()
                                         and ours(record.get('repository'), record.get('git_common_dir'))):
            item = entry(record['branch'])
            item['worktrees'].append(workspace)
            item['ownership_records'].append(str(path))
    return items


def _evaluate(repo, item, target, worktrees, discard, purge_history=False):
    branch, reasons = item['branch'], []
    if item.get('orca_lite_unsettled'):
        reasons.append('Orca lite settlement/accounting pending; inspect runtime first')
    sha = _branch_sha(repo, branch)
    item['exists'] = bool(sha)
    if branch in PROTECTED or branch == target:
        item.update(action='keep', reasons=['protected branch'])
        return item
    if not sha:
        # Branch already gone: only DevFlow records remain.
        closed = all(r['status'] in state.FINAL_STATES for r in item['runs'])
        if not closed:
            reasons.append('run still active')
        if item['worktrees']:
            reasons.append('worktree registered without its branch; inspect manually')
        if not purge_history:
            reasons.append(HISTORY)
        item.update(merged=None, action='keep' if reasons else 'forget', reasons=reasons)
        return item
    item['merged'] = _is_ancestor(repo, sha, target)
    if any(r['status'] not in state.FINAL_STATES for r in item['runs']):
        reasons.append('run still active; close it first')
    owned = {_norm(w) for w in item['worktrees']}
    for path, checked_out in worktrees.items():
        if checked_out == branch and path not in owned:
            reasons.append(f'checked out in {path}; switch that checkout to another branch first')
    for workspace in item['worktrees']:
        checked_out = worktrees.get(_norm(workspace))
        if checked_out in PROTECTED or checked_out == target:
            reasons.append(f'owned worktree contains protected branch {checked_out}; restore the primary checkout first')
        elif checked_out and checked_out != branch:
            reasons.append(f'owned worktree changed branch to {checked_out}; reconcile ownership first')
        try:
            dirty = gitops.inspect(workspace)['dirty']
        except DevFlowError:
            reasons.append(f'worktree not accessible: {workspace}; inspect manually')
            continue
        if dirty:
            reasons.append(f'uncommitted changes in worktree {workspace}')
    if not item['merged'] and branch not in discard:
        reasons.append(f'not merged into {target} (if it was squash-merged, confirm and use --discard)')
    item.update(sha=sha, action='keep' if reasons else 'remove', reasons=reasons,
                discard=branch in discard and not item['merged'])
    return item


def _is_ancestor(repo, sha, target):
    try:
        gitops.git(repo, 'merge-base', '--is-ancestor', sha, target)
        return True
    except DevFlowError:
        return False


def _forget(data, item, purge_history=False):
    if not purge_history:
        return
    for path in item['lite_records']:
        Path(inside(Path(path), Path(data) / 'lite')).unlink(missing_ok=True)
    for run in item['runs']:
        folder = Path(run['dir'])
        safe_id(folder.name)
        if run['status'] in state.FINAL_STATES and folder.parent.resolve() == (Path(data) / 'runs').resolve():
            shutil.rmtree(folder)


def cleanup(data, repository, apply=False, discard=(), into=None, purge_history=False,
            remote=None, orca_idle_confirmed=False):
    info = gitops.inspect(repository)
    repo = info['workspace']
    worktrees = _worktrees(repo)
    target = target_branch(repo, into)
    discard = set(discard)
    items = [_evaluate(repo, item, target, worktrees, discard, purge_history)
             for item in _records(data, set(worktrees), _norm(gitops.common_dir(repo))).values()]
    if remote is not None and (remote.startswith('-') or remote not in gitops.git(repo, 'remote').splitlines()):
        raise DevFlowError('Remote cleanup requires an explicitly named configured remote')
    for item in items:
        records = [read_json(path) for path in item['ownership_records']]
        item['workspace_backends'] = [r.get('backend', 'git') for r in records]
        item['runtime_check_required'] = 'orca' in item['workspace_backends']
        item['remote_branch'] = None
        if remote:
            ref = 'refs/heads/' + item['branch']
            lines = gitops.git(repo, 'ls-remote', '--heads', remote, ref).splitlines()
            matches = [line.split()[0] for line in lines if len(line.split()) == 2 and line.split()[1] == ref]
            sha = matches[0] if matches else None
            merged = _is_ancestor(repo, sha, target) if sha else None
            item['remote_branch'] = {'remote': remote, 'ref': ref, 'exists': bool(sha), 'sha': sha, 'merged': merged}
            if sha and not merged:
                item['reasons'].append('remote revision not proven integrated; retain local and remote branch')
                item['action'] = 'keep'
            elif sha and not item['exists'] and item['action'] == 'keep':
                blockers = [r for r in item['reasons'] if r != HISTORY]
                if not blockers:
                    item.update(action='remove_remote', reasons=[])
    unknown = discard - {i['branch'] for i in items}
    if unknown:
        raise DevFlowError('Only DevFlow-recorded branches can be discarded: ' + ', '.join(sorted(unknown)))
    # Gone branches whose only reason to stay is retained history need no action: summarize, do not list.
    retained = sorted(i['branch'] for i in items if i['action'] == 'keep' and i['reasons'] == [HISTORY])
    items = [i for i in items if i['branch'] not in retained]
    result = {'repository': repo, 'into': target, 'applied': apply,
              'purge_history': purge_history, 'history_preserved': not purge_history, 'remote': remote,
              'history_retained': {'count': len(retained), 'branches': retained[:20]},
              'items': [{k: v for k, v in i.items() if k not in ('lite_records', 'ownership_records')}
                        | {'runs': [{'run_id': r['run_id'], 'status': r['status']} for r in i['runs']]}
                        for i in items]}
    if not apply:
        result['next_action'] = 'Show this list to the user; run cleanup --apply only after explicit confirmation'
        if retained:
            result['next_action'] += (f'; {len(retained)} gone branch(es) only keep DevFlow history '
                                      '(cleanup --purge-history lists them for explicit removal)')
        return result
    removed, errors = [], []
    for item in items:
        if item['action'] not in ('remove', 'forget', 'remove_remote'):
            continue
        try:
            if item['runtime_check_required'] and not orca_idle_confirmed:
                raise DevFlowError('Inspect Orca workers/terminals first; --orca-idle-confirmed records Coordinator confirmation')
            # Recheck ownership and cleanliness just before any deletion.
            for workspace in item['worktrees']:
                fresh = gitops.inspect(workspace)
                if fresh['dirty'] or fresh['branch'] not in ('', item['branch']):
                    raise DevFlowError('Owned workspace changed since preview/evaluation; nothing removed')
                if item.get('discard') and fresh['revision'] != item['sha']:
                    raise DevFlowError('Discarded branch moved since evaluation; nothing removed')
                if not item.get('discard') and not _is_ancestor(repo, fresh['revision'], target):
                    raise DevFlowError('Workspace HEAD is not integrated; nothing removed')
            for workspace, record in zip(item['worktrees'], item['ownership_records']):
                # No --force: Git refuses worktrees with modified or untracked files.
                ownership = read_json(record)
                if ownership.get('backend') == 'orca':
                    if not _orca_workspace(ownership, 'show')['exists']:
                        raise DevFlowError('Orca workspace identity missing before deletion; reconcile first')
                    try:
                        _orca_workspace(ownership, 'remove')
                    except DevFlowError:
                        # A lost response is not a failed operation: reconcile both authorities.
                        if _norm(workspace) in _worktrees(repo) or _orca_workspace(ownership, 'show')['exists']:
                            raise
                    if _orca_workspace(ownership, 'show')['exists']:
                        raise DevFlowError('Orca still lists the workspace after removal')
                else:
                    gitops.git(repo, 'worktree', 'remove', workspace)
                if _norm(workspace) in _worktrees(repo) or Path(workspace).exists():
                    raise DevFlowError('Workspace removal incomplete; residual path preserved for explicit recovery')
                ownership['removed_at'] = now()
                atomic_write(Path(record), json_bytes(ownership))
            deleted_remote = False
            remote_branch = item['remote_branch']
            if remote_branch and remote_branch['exists']:
                ref = remote_branch['ref']
                gitops.git(repo, 'push', '--force-with-lease=' + ref + ':' + remote_branch['sha'], remote, '--delete', item['branch'])
                if gitops.git(repo, 'ls-remote', '--heads', remote, ref):
                    raise DevFlowError('Remote branch still exists after deletion')
                deleted_remote = True
            if item['action'] == 'remove':
                # Expected old value makes deletion fail if the branch moved after evaluation.
                # Orca may already have deleted the integrated checked-out branch.
                current_sha = _branch_sha(repo, item['branch'])
                if current_sha is not None:
                    gitops.git(repo, 'update-ref', '-d', 'refs/heads/' + item['branch'], item['sha'])
                if _branch_sha(repo, item['branch']) is not None:
                    raise DevFlowError('Local branch still exists after cleanup')
            _forget(data, item, purge_history)
            removed.append({'branch': item['branch'], 'deleted_branch': item['action'] == 'remove',
                            'deleted_remote_branch': deleted_remote,
                            'removed_worktrees': item['worktrees'], 'discarded_unmerged': item.get('discard', False)})
        except (DevFlowError, OSError) as exc:
            errors.append({'branch': item['branch'], 'error': str(exc)})
    result.update(removed=removed, errors=errors)
    return result
