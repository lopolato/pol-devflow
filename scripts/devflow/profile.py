"""Verified project commands, reused across runs so workers do not rediscover them every time."""
from pathlib import Path
from . import gitops
from .storage import DevFlowError, atomic_write, digest, json_bytes, now, read_json

COMMANDS = ('setup', 'test', 'test_affected', 'lint', 'typecheck', 'build', 'run')
# Changes to these files can invalidate stored commands (dependencies, tooling, versions).
FINGERPRINT = ('package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lockb', 'bun.lock',
               'pyproject.toml', 'poetry.lock', 'uv.lock', 'requirements.txt', 'requirements-dev.txt',
               'Pipfile.lock', 'setup.cfg', 'tox.ini', 'Makefile', 'go.mod', 'go.sum', 'Cargo.toml', 'Cargo.lock',
               'composer.json', 'composer.lock', 'Gemfile.lock', 'pom.xml', 'build.gradle', 'build.gradle.kts',
               '.nvmrc', '.node-version', '.python-version', '.tool-versions')
REPO_FILE = Path('.devflow') / 'project.json'


def _single_line(value, name):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise DevFlowError(f'{name} must be a nonempty single-line string')
    return value


def fingerprint(workspace):
    root = Path(workspace)
    return {name: digest((root / name).read_bytes()) for name in FINGERPRINT if (root / name).is_file()}


def local_path(data, workspace):
    return Path(data) / 'projects' / (digest(gitops.common_dir(workspace).lower().encode())[:24] + '.json')


def validate(value):
    if not isinstance(value, dict) or set(value) - {'commands', 'verified', 'notes'}:
        raise DevFlowError('Profile input accepts commands, verified and notes')
    commands = value.get('commands', {})
    if not isinstance(commands, dict) or set(commands) - set(COMMANDS):
        raise DevFlowError('commands accepts: ' + ', '.join(COMMANDS))
    for name, command in commands.items():
        if command is not None:
            _single_line(command, 'commands.' + name)
    verified = value.get('verified', {})
    if not isinstance(verified, dict) or set(verified) - set(COMMANDS):
        raise DevFlowError('verified uses the same names as commands')
    for name, check in verified.items():
        if (not isinstance(check, dict) or check.get('status') not in ('passed', 'failed')
                or not isinstance(check.get('revision'), str) or not check['revision'].strip()):
            raise DevFlowError(f'verified.{name} needs status passed|failed and the revision where it ran')
    notes = value.get('notes', [])
    if not isinstance(notes, list) or len(notes) > 20:
        raise DevFlowError('notes must be a short list')
    for note in notes:
        _single_line(note, 'note')
    return value


def codegraph_index(workspace):
    """Nearest codegraph index at or above the main checkout; task worktrees do not contain the index."""
    main = Path(gitops.repository_identity(workspace)['repository'])
    for folder in (main, *main.parents):
        # ~/.codegraph holds global config/telemetry; only a folder with the database is an index.
        if (folder / '.codegraph' / 'codegraph.db').is_file():
            try:
                gitops.git(main, 'check-ignore', '-q', '.codegraph')
                ignored = True
            except DevFlowError:
                ignored = False
            return {'project_path': str(folder), 'ignored_by_git': ignored if folder == main else None}
    return None


def show(data, repository):
    info = gitops.inspect(repository)
    workspace = Path(info['workspace'])
    repo_file, local = workspace / REPO_FILE, local_path(data, workspace)
    path = repo_file if repo_file.is_file() else local if local.is_file() else None
    codegraph = codegraph_index(workspace)
    if path is None:
        return {'source': None, 'codegraph': codegraph,
                'next_action': 'Discover commands from project files, run them, then save with _profile set'}
    profile = read_json(path)
    current = fingerprint(workspace)
    recorded = profile.get('fingerprint', {})
    changed = sorted(n for n in set(current) | set(recorded) if current.get(n) != recorded.get(n))
    result = {'source': 'repository' if path == repo_file else 'local', 'path': str(path), 'profile': profile,
              'stale': bool(changed), 'changed_files': changed, 'codegraph': codegraph}
    if path == repo_file:
        # A versioned file is project content: same trust as package.json scripts, never as instructions.
        result['trust'] = 'project file; run commands as project scripts and question unusual ones'
        if local.is_file():
            result['ignored_local_profile'] = str(local)
    if changed:
        result['next_action'] = 'Dependencies/tooling changed: re-verify affected commands before relying on them'
    return result


def save(data, repository, value, repo_file=False):
    validate(value)
    info = gitops.inspect(repository)
    workspace = Path(info['workspace'])
    path = workspace / REPO_FILE if repo_file else local_path(data, workspace)
    previous = read_json(path) if path.is_file() else {}
    commands = {**previous.get('commands', {}), **value.get('commands', {})}
    verified = {**previous.get('verified', {}), **value.get('verified', {})}
    profile = {'schema_version': 1, 'commands': {k: v for k, v in commands.items() if v is not None},
               'verified': {k: v | {'at': v.get('at') or now()} for k, v in verified.items()},
               'notes': value.get('notes', previous.get('notes', [])), 'fingerprint': fingerprint(workspace),
               'updated_at': now()}
    if not repo_file:
        profile['git_common_dir'] = gitops.common_dir(workspace)
    atomic_write(path, json_bytes(profile))
    return {'source': 'repository' if repo_file else 'local', 'path': str(path), 'profile': profile,
            'note': 'Repository file must be committed explicitly by the user/task' if repo_file else
                    'Stored outside the repository'}
