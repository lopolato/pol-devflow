"""Owned installation manifests and all-or-nothing model regeneration."""
import copy
import json
import re
import tomllib
from pathlib import Path
from . import adapters, config
from . import __version__
from .storage import (DevFlowError, FileLock, digest, inside, json_bytes, now,
                      package_root, read_json, reject_symlink, transaction)


def manifest_path(data, runtime):
    if runtime not in config.RUNTIMES:
        raise DevFlowError('Unknown runtime')
    return Path(data) / 'installations' / (runtime + '.json')


def managed_path(home, relative, runtime):
    path = Path(relative)
    allowed_agents = {f'agents/pol-{r}.{"toml" if runtime == "codex" else "md"}' for r in config.WORKER_ROLES}
    posix = path.as_posix()
    if path.is_absolute() or '..' in path.parts or (posix not in allowed_agents and not posix.startswith('skills/pol-devflow/')):
        raise DevFlowError(f'Manifest contains an unowned path: {relative}')
    # Check before resolving; an in-root symlink otherwise hides its unowned target.
    reject_symlink(Path(home) / path)
    target = inside(Path(home) / path, home)
    reject_symlink(target)
    return target


def load_manifest(data, runtime):
    path = manifest_path(data, runtime)
    if not path.exists():
        return None
    value = read_json(path)
    if (not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('runtime') != runtime
            or not isinstance(value.get('files'), dict) or not value.get('runtime_home')):
        raise DevFlowError('Invalid installation manifest')
    for relative, hashed in value['files'].items():
        managed_path(value['runtime_home'], relative, runtime)
        if not re.fullmatch(r'[a-f0-9]{64}', hashed):
            raise DevFlowError('Invalid manifest hash')
    return value


def source_files(root):
    root = Path(root)
    for top in ('SKILL.md', 'README.md', 'VERIFICATION.md', 'agents', 'config', 'core', 'scripts', 'adapters', 'tests'):
        path = root / top
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else sorted(path.rglob('*'))
        for source in candidates:
            if (source.is_file() and '__pycache__' not in source.parts
                    and source.suffix != '.pyc' and not source.is_symlink()):
                yield source.relative_to(root).as_posix(), source.read_bytes()


def skill_for_runtime(content, runtime):
    if runtime == 'claude':
        text = content.decode('utf-8').replace('\r\n', '\n')
        if not text.startswith('---\n'):
            raise DevFlowError('Skill frontmatter is missing')
        parts = text.split('---\n', 2)
        if len(parts) != 3:
            raise DevFlowError('Skill frontmatter is not closed')
        header = re.sub(r'(?m)^(?:disable-model-invocation|argument-hint):[^\n]*\n', '', parts[1])
        text = ('---\ndisable-model-invocation: true\n'
                'argument-hint: "<error|feature|optimize|help|status|config|cleanup> [arguments]"\n'
                + header + '---\n' + parts[2])
        return text.encode('utf-8')
    return content


def install(data, runtime, runtime_home, root=None):
    root, home = Path(root or package_root()).resolve(), Path(runtime_home).resolve()
    reject_symlink(runtime_home)
    validate(root)
    with FileLock(Path(data) / 'configuration.lock', 'install-' + runtime):
        existing = load_manifest(data, runtime)
        if existing and Path(existing['runtime_home']).resolve() != home:
            raise DevFlowError('Runtime already registered at another home; uninstall that installation first')
        selected = config.load(config.active_path(data, root))
        changes, hashes = {}, {}
        for relative, content in source_files(root):
            if relative == 'SKILL.md':
                content = skill_for_runtime(content, runtime)
            destination = 'skills/pol-devflow/' + relative
            target = managed_path(home, destination, runtime)
            if target.exists():
                expected = (existing or {}).get('files', {}).get(destination)
                if expected is None or digest(target.read_bytes()) != expected:
                    raise DevFlowError(f'Existing or manually modified file; no overwrite: {target}')
            changes[target] = content
            hashes[destination] = digest(content)
        for filename, text in adapters.render_all(runtime, selected, root).items():
            relative = 'agents/' + filename
            target = managed_path(home, relative, runtime)
            if target.exists():
                expected = (existing or {}).get('files', {}).get(relative)
                if expected is None or digest(target.read_bytes()) != expected:
                    raise DevFlowError(f'Existing or manually modified agent; no overwrite: {target}')
            content = text.encode('utf-8')
            changes[target] = content
            hashes[relative] = digest(content)
        # Preserve previously owned files no longer in this release; uninstall still knows them.
        if existing:
            for relative, hashed in existing['files'].items():
                if relative not in hashes:
                    hashes[relative] = hashed
        shared = Path(data) / 'config/models.yaml'
        if not shared.exists():
            changes[shared] = json_bytes(selected)
        manifest = {'schema_version': 1, 'runtime': runtime, 'runtime_home': str(home),
                    'installed_at': now(), 'source_version': __version__, 'files': hashes}
        changes[manifest_path(data, runtime)] = json_bytes(manifest)
        backup = transaction(changes, Path(data) / 'backups')
        return {'runtime': runtime, 'runtime_home': str(home), 'files': len(hashes), 'backup': backup,
                'message': 'Installed only owned files; existing runtime settings were not changed'}


def config_set(data, runtime, role, model=None, effort=None, inherit=False, root=None):
    root = Path(root or package_root()).resolve()
    # Validate before creating lock directories or writing anything.
    current = config.load(config.active_path(data, root))
    config.changed(current, runtime, role, model, effort, inherit)
    with FileLock(Path(data) / 'configuration.lock', 'config-set'):
        current = config.load(config.active_path(data, root))
        proposed = config.changed(current, runtime, role, model, effort, inherit)
        rendered = adapters.render_all(runtime, proposed, root)
        manifest = load_manifest(data, runtime)
        changes = {}
        if manifest:
            home = Path(manifest['runtime_home'])
            for filename, text in rendered.items():
                relative = 'agents/' + filename
                target = managed_path(home, relative, runtime)
                expected = manifest['files'].get(relative)
                if expected is None or not target.is_file() or digest(target.read_bytes()) != expected:
                    raise DevFlowError(f'Generated profile modified/missing: {target}; configuration was not changed')
                content = text.encode('utf-8')
                changes[target] = content
                manifest['files'][relative] = digest(content)
            manifest['configured_at'] = now()
            changes[manifest_path(data, runtime)] = json_bytes(manifest)
        destination = Path(data) / 'config/models.yaml'
        changes[destination] = json_bytes(proposed)
        backup = transaction(changes, Path(data) / 'backups')
        return {'config_path': str(destination), 'runtime': runtime, 'role': role,
                'settings': proposed['profiles'][role][runtime], 'regenerated': bool(manifest),
                'model_availability': 'not_verified', 'effective': 'future runs only', 'backup': backup}


def uninstall(data, runtime):
    if not manifest_path(data, runtime).exists():
        return {'removed': [], 'preserved': [], 'message': 'No registered installation'}
    with FileLock(Path(data) / 'configuration.lock', 'uninstall-' + runtime):
        manifest = load_manifest(data, runtime)
        changes, removed, preserved, retained = {}, [], [], {}
        for relative, hashed in manifest['files'].items():
            target = managed_path(manifest['runtime_home'], relative, runtime)
            if not target.exists():
                continue
            if not target.is_file() or digest(target.read_bytes()) != hashed:
                preserved.append(str(target))
                retained[relative] = hashed
            else:
                changes[target] = None
                removed.append(str(target))
        if retained:
            manifest['files'] = retained
            manifest['status'] = 'uninstalled_with_preserved_changes'
            changes[manifest_path(data, runtime)] = json_bytes(manifest)
        else:
            changes[manifest_path(data, runtime)] = None
        backup = transaction(changes, Path(data) / 'backups')
        return {'removed': removed, 'preserved': preserved, 'backup': backup,
                'message': 'Shared config, runs, branches and worktrees preserved; empty directories may remain'}


def validate(root=None):
    root = Path(root or package_root())
    required = ['SKILL.md', 'agents/openai.yaml', 'config/models.yaml', 'adapters/orca/README.md',
                'core/rules/technical-context.md', 'scripts/devflow/orca.py']
    required += [f'core/agents/{r}.md' for r in config.ROLES]
    required += [f'core/workflows/{m}.md' for m in ('error', 'feature', 'optimize', 'lite')]
    required += [f'core/rules/{r}.md' for r in ('worker-contract', 'grill-me', 'git-worktrees', 'handoff',
                                             'context-sharing', 'scope-control', 'definition-of-done', 'recovery-loop', 'project-memory')]
    required += [f'core/templates/{t}.md' for t in ('task-context', 'agent-result', 'review-result', 'final-report')]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise DevFlowError('Missing required package files: ' + ', '.join(missing))
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    if not skill.startswith('---\n') or 'name: pol-devflow' not in skill.split('---')[1]:
        raise DevFlowError('Invalid skill name/frontmatter')
    if 'allow_implicit_invocation: false' not in (root / 'agents/openai.yaml').read_text(encoding='utf-8'):
        raise DevFlowError('Explicit-only Codex invocation policy is required')
    for doc in list((root / 'core').rglob('*.md')) + [root / 'SKILL.md']:
        text = doc.read_text(encoding='utf-8')
        for link in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', text):
            if '://' not in link and not (doc.parent / link).resolve().is_file():
                raise DevFlowError(f'Broken reference in {doc.name}: {link}')
    value = config.load(root / 'config/models.yaml')
    counts = {runtime: len(adapters.render_all(runtime, value, root)) for runtime in config.RUNTIMES}
    return {'status': 'healthy', 'profiles': len(config.ROLES), 'generated_workers': counts,
            'validation_scope': 'portable_package', 'model_availability': 'not_verified',
            'runtime_orchestration': 'requires native session tools'}


def validate_installed(data, runtime):
    manifest = load_manifest(data, runtime)
    if not manifest:
        raise DevFlowError('No registered installation for ' + runtime)
    home = Path(manifest['runtime_home'])
    root = home / 'skills/pol-devflow'
    if runtime == 'claude':
        text = (root / 'SKILL.md').read_text(encoding='utf-8')
        parts = text.split('---\n', 2)
        values = re.findall(r'(?m)^disable-model-invocation:[ \t]*([^\n]*)$', parts[1] if len(parts) == 3 else '')
        if values != ['true']:
            raise DevFlowError('Installed Claude skill requires exactly one disable-model-invocation: true')
    result = validate(root)
    for relative, expected in manifest['files'].items():
        path = managed_path(home, relative, runtime)
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise DevFlowError(f'Installed file missing/modified: {path}')
    return result | {'validation_scope': 'installed_runtime', 'runtime': runtime,
                     'source_version': manifest['source_version'], 'verified_files': len(manifest['files'])}


def validate_context(data, root, runtime=None):
    if runtime:
        return validate_installed(data, runtime)
    for candidate in config.RUNTIMES:
        manifest = load_manifest(data, candidate)
        if manifest and Path(root).resolve() == (Path(manifest['runtime_home']) / 'skills/pol-devflow').resolve():
            return validate_installed(data, candidate)
    return validate(root)
