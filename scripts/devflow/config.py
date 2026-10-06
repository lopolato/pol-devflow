"""One model configuration; JSON is the dependency-free YAML-compatible format."""
import copy
import json
from pathlib import Path
from .storage import DevFlowError, package_root, unique_pairs

ROLES = ('coordinator', 'architect', 'explorer', 'implementer', 'debugger', 'fixer', 'tester', 'reviewer', 'lite')
WORKER_ROLES = tuple(r for r in ROLES if r != 'coordinator')
# Lite works outside recorded runs; full-mode assignments never use it.
TASK_ROLES = tuple(r for r in WORKER_ROLES if r != 'lite')
RUNTIMES = ('codex', 'claude')
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def defaults():
    return {'schema_version': 1, 'profiles': {r: {rt: {} for rt in RUNTIMES} for r in ROLES}}


def active_path(data, root=None):
    shared = Path(data) / 'config' / 'models.yaml'
    return shared if shared.exists() else Path(root or package_root()) / 'config' / 'models.yaml'


def validate(value):
    if not isinstance(value, dict) or set(value) != {'schema_version', 'profiles'} or value['schema_version'] != 1:
        raise DevFlowError('Model config needs schema_version: 1 and profiles')
    profiles = value['profiles']
    if not isinstance(profiles, dict) or set(profiles) != set(ROLES):
        raise DevFlowError('Config must define exactly the nine DevFlow profiles')
    for role, mappings in profiles.items():
        if not isinstance(mappings, dict) or set(mappings) != set(RUNTIMES):
            raise DevFlowError(f'{role}: expected codex and claude mappings')
        for runtime, settings in mappings.items():
            if not isinstance(settings, dict) or set(settings) - {'model', 'effort'}:
                raise DevFlowError(f'{role}/{runtime}: only model and effort are supported')
            if role == 'coordinator' and settings:
                raise DevFlowError('Coordinator configuration must inherit the main session')
            model = settings.get('model')
            if model is not None and (not isinstance(model, str) or not model.strip() or any(ord(c) < 32 for c in model)):
                raise DevFlowError('Model must be a nonempty single-line string')
            if 'effort' in settings and (runtime != 'codex' or settings['effort'] not in EFFORTS):
                raise DevFlowError(f'Unsupported effort for {runtime}; model-specific availability is not verified')
    return value


def load(path):
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
        try:
            value = json.loads(text, object_pairs_hook=unique_pairs)
        except json.JSONDecodeError:
            try:
                import yaml
            except ImportError as exc:
                raise DevFlowError('Use JSON syntax (valid YAML), config set, or install optional PyYAML to read block YAML') from exc
            class UniqueLoader(yaml.SafeLoader):
                pass
            def mapping(loader, node):
                return unique_pairs([(loader.construct_object(k), loader.construct_object(v)) for k, v in node.value])
            UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
            value = yaml.load(text, Loader=UniqueLoader)
        # Pre-lite V1 installations have eight profiles. Normalize in memory only;
        # reading configuration must not rewrite the user's model choices.
        if (isinstance(value, dict) and value.get('schema_version') == 1
                and isinstance(value.get('profiles'), dict)
                and set(value['profiles']) == set(ROLES) - {'lite'}):
            value['profiles']['lite'] = {'codex': {}, 'claude': {}}
        return validate(value)
    except DevFlowError:
        raise
    except Exception as exc:
        raise DevFlowError(f'Invalid model config {path}: {exc}') from exc


def changed(value, runtime, role, model=None, effort=None, inherit=False):
    validate(value)
    if runtime not in RUNTIMES or role not in WORKER_ROLES:
        raise DevFlowError('Choose codex/claude and a worker role; coordinator uses the main session')
    if inherit and (model is not None or effort is not None):
        raise DevFlowError('--inherit cannot be combined with --model or --effort')
    if not inherit and model is None and effort is None:
        raise DevFlowError('Specify model, effort or inherit')
    result = copy.deepcopy(value)
    settings = result['profiles'][role][runtime]
    if inherit:
        settings.clear()
    else:
        if model is not None:
            settings['model'] = model
        if effort is not None:
            settings['effort'] = effort
    return validate(result)
