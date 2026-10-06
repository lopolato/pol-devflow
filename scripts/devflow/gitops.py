"""Conservative Git support: no main writes, reset, stash, push or force cleanup."""
import re
import subprocess
import uuid
from pathlib import Path
from .storage import DevFlowError, atomic_write, json_bytes, now, read_json, reject_symlink


def git(workspace, *args):
    try:
        process = subprocess.run(['git', *args], cwd=workspace, capture_output=True,
                                 encoding='utf-8', errors='replace', timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DevFlowError(f'Git unavailable/timeout: {exc}') from exc
    if process.returncode:
        raise DevFlowError(f'git {args[0]} failed: {process.stderr.strip()}')
    return process.stdout.rstrip('\r\n')


def inspect(workspace):
    workspace = Path(workspace).resolve()
    root = Path(git(workspace, 'rev-parse', '--show-toplevel')).resolve()
    revision = git(root, 'rev-parse', 'HEAD')
    branch = git(root, 'branch', '--show-current')
    status = git(root, 'status', '--porcelain=v1', '-uall')
    return {'workspace': str(root), 'revision': revision, 'branch': branch, 'dirty': bool(status),
            'status_porcelain': status}


def common_dir(workspace):
    """Stable repository identity shared by the main checkout and every linked worktree."""
    return str((Path(workspace) / git(workspace, 'rev-parse', '--git-common-dir')).resolve())


def repository_identity(workspace):
    main = git(workspace, 'worktree', 'list', '--porcelain').splitlines()[0].removeprefix('worktree ')
    return {'repository': str(Path(main).resolve()), 'git_common_dir': common_dir(workspace)}


def changed_paths(workspace, base):
    # NUL-delimited names handle spaces, Unicode, quotes and rename source paths.
    tracked = git(workspace, 'diff', '--no-renames', '--name-only', '-z', base, 'HEAD', '--')
    staged = git(workspace, 'diff', '--cached', '--no-renames', '--name-only', '-z', 'HEAD', '--')
    unstaged = git(workspace, 'diff', '--no-renames', '--name-only', '-z', '--')
    untracked = git(workspace, 'ls-files', '--others', '--exclude-standard', '-z')
    return (set(tracked.split('\0')) | set(staged.split('\0'))
            | set(unstaged.split('\0')) | set(untracked.split('\0'))) - {''}


def branch_name(mode, description):
    slug = re.sub(r'[^a-z0-9]+', '-', description.lower()).strip('-')[:50] or 'task'
    prefix = {'error': 'fix', 'feature': 'feature', 'optimize': 'optimize'}[mode]
    return f'{prefix}/{slug}-{uuid.uuid4().hex[:8]}'


def lite_branch(repository, mode, description, base=None):
    """Create a task branch in the current checkout; no worktree, so local dependencies/config keep working."""
    if mode not in ('error', 'feature'):
        raise DevFlowError('Lite supports error and feature only')
    return task_branch(repository, mode, description, base)


def task_branch(repository, mode, description, base=None):
    if mode not in ('error', 'feature', 'optimize'):
        raise DevFlowError('Invalid task mode')
    info = inspect(repository)
    if info['dirty']:
        raise DevFlowError('Lite needs a clean checkout; preserve the local changes and use full mode or resolve them first')
    root = info['workspace']
    start = git(root, 'rev-parse', '--verify', (base + '^{commit}') if base else 'HEAD')
    branch = branch_name(mode, description)
    git(root, 'switch', '-c', branch, start)
    return inspect(root) | {'base_revision': start, 'previous_branch': info['branch'], 'isolated': False}


def prepare(repository, mode, description, worktree_root, base=None, existing_branch=None, _parent=None):
    if mode not in ('error', 'feature', 'optimize'):
        raise DevFlowError('Invalid Git task mode')
    info = inspect(repository)
    root = info['workspace']
    if existing_branch:
        if info['branch'] != existing_branch or existing_branch in ('main', 'master'):
            raise DevFlowError('Explicit task branch must be currently checked out and cannot be main/master')
        if base:
            raise DevFlowError('Cannot combine existing branch reuse with a new base')
        return info | {'base_revision': info['revision'], 'isolated': False, 'preexisting_dirty': info['dirty']}
    start = git(root, 'rev-parse', '--verify', (base + '^{commit}') if base else 'HEAD')
    branch = branch_name(mode, description)
    folder = Path(worktree_root).resolve()
    reject_symlink(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('wt-' + uuid.uuid4().hex[:12])
    git(root, 'worktree', 'add', '-b', branch, str(target), start)
    ownership = {'schema_version': 1, 'kind': 'child' if _parent else 'root', **repository_identity(root),
                 'workspace': str(target.resolve()), 'branch': branch, 'base_revision': start,
                 'parent_workspace': _parent['workspace'] if _parent else None,
                 'parent_branch': _parent['branch'] if _parent else None, 'created_at': now()}
    # Missing provenance leaves the worktree intact and ineligible for automatic cleanup.
    atomic_write(folder / '.devflow-ownership' / (target.name + '.json'), json_bytes(ownership))
    return inspect(target) | {'base_revision': start, 'isolated': True, 'preexisting_dirty': info['dirty']}


def check_task_workspace(workspace, expected_branch=None):
    info = inspect(workspace)
    if not info['branch'] or info['branch'] in ('main', 'master'):
        raise DevFlowError('Mutating Git operations require a task branch, never main/master or detached HEAD')
    if expected_branch and info['branch'] != expected_branch:
        raise DevFlowError('Checked out branch differs from the recorded task branch')
    return info


def owned_paths(workspace, paths):
    root = Path(workspace).resolve()
    if not paths:
        raise DevFlowError('Provide explicit owned paths')
    result = []
    for value in paths:
        path = Path(value)
        if path.is_absolute() or '..' in path.parts or ':' in value or value.startswith('-') or value in ('.', ''):
            raise DevFlowError('Commit paths must be explicit relative files, without traversal or pathspecs')
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root) or resolved.is_dir() or any(c in value for c in '*?['):
            raise DevFlowError('Commit paths cannot be directories, patterns or outside workspace')
        result.append(path.as_posix())
    return result


def commit(workspace, paths, message, expected_branch=None):
    info = check_task_workspace(workspace, expected_branch)
    paths = owned_paths(info['workspace'], paths)
    staged = git(workspace, 'diff', '--cached', '--name-only', '-z')
    staged_paths = set(staged.split('\0')) - {''}
    if staged_paths - set(paths):
        raise DevFlowError('Unrelated paths are already staged; preserve staging and reconcile first')
    if not message.strip():
        raise DevFlowError('Commit message is required')
    git(workspace, 'add', '--', *paths)
    # Verify the exact staged paths, including any path introduced via a rename.
    staged_paths = set(git(workspace, 'diff', '--cached', '--name-only', '-z').split('\0')) - {''}
    if not staged_paths or staged_paths - set(paths):
        raise DevFlowError('Staged diff is empty or contains paths outside the explicit assignment; inspect before continuing')
    git(workspace, 'diff', '--cached', '--check')
    git(workspace, 'commit', '-m', message)
    return git(workspace, 'rev-parse', 'HEAD')


def child(workspace, name, worktree_root):
    info = check_task_workspace(workspace)
    if info['dirty']:
        raise DevFlowError('Commit the root checkpoint before creating a child')
    return prepare(workspace, 'feature', name, worktree_root, base=info['revision'], _parent=info)


def integrate(workspace, child_branch, expected_branch=None):
    info = check_task_workspace(workspace, expected_branch)
    if info['dirty']:
        raise DevFlowError('Integration requires a clean root workspace')
    if child_branch in ('main', 'master') or child_branch.startswith('-'):
        raise DevFlowError('Only task branches can be integrated')
    git(workspace, 'check-ref-format', '--branch', child_branch)
    git(workspace, 'rev-parse', '--verify', 'refs/heads/' + child_branch)
    git(workspace, 'merge', '--no-ff', '--no-edit', child_branch)
    return inspect(workspace)


def remove_integrated_child(root_workspace, child_workspace, workers_active=False):
    root = check_task_workspace(root_workspace)
    child_info = inspect(child_workspace)
    target = Path(child_info['workspace']).resolve()
    if workers_active or child_info['dirty'] or target == Path(root['workspace']).resolve():
        raise DevFlowError('Cannot remove active, dirty or root worktree')
    ownership_path = target.parent / '.devflow-ownership' / (target.name + '.json')
    ownership = read_json(ownership_path)
    if (ownership.get('schema_version') != 1 or ownership.get('kind') != 'child'
            or Path(ownership.get('workspace', '')).resolve() != target
            or ownership.get('branch') != child_info['branch']
            or Path(ownership.get('parent_workspace', '')).resolve() != Path(root['workspace']).resolve()
            or ownership.get('parent_branch') != root['branch']):
        raise DevFlowError('Cleanup target is not an owned child of this root; preserve the worktree')
    git(root_workspace, 'merge-base', '--is-ancestor', child_info['revision'], root['revision'])
    listing = git(root_workspace, 'worktree', 'list', '--porcelain')
    expected_line = 'worktree ' + target.as_posix()
    if not any(line.replace('\\', '/') == expected_line for line in listing.splitlines()):
        raise DevFlowError('Target is not a registered worktree of this repository')
    reject_symlink(target)
    git(root_workspace, 'worktree', 'remove', str(target))
    ownership['removed_at'] = now()
    atomic_write(ownership_path, json_bytes(ownership))
    return {'removed_workspace': str(target), 'branch_preserved': child_info['branch']}
