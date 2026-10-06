"""Generate runtime-native workers without duplicating workflow policies."""
import json
import tomllib
from pathlib import Path
from . import config
from .storage import DevFlowError, package_root


def instructions(role, root=None):
    root = Path(root or package_root())
    if role == 'lite':
        return (root / 'core' / 'agents' / 'lite.md').read_text(encoding='utf-8')
    return ((root / 'core' / 'rules' / 'worker-contract.md').read_text(encoding='utf-8') +
            '\n\n' + (root / 'core' / 'agents' / f'{role}.md').read_text(encoding='utf-8'))


def render_all(runtime, settings, root=None):
    config.validate(settings)
    if runtime not in config.RUNTIMES:
        raise DevFlowError('Unknown runtime')
    result = {}
    for role in config.WORKER_ROLES:
        name = f'pol-{role}'
        desc = (f'DevFlow {role}; use only for a Coordinator-assigned DevFlow task.' if role != 'lite' else
                'DevFlow lite; use only when the DevFlow Coordinator delegates a small lite task.')
        body = instructions(role, root)
        selected = settings['profiles'][role][runtime]
        if runtime == 'codex':
            lines = ['# GENERATED FILE: edit core/agents or centralized models.yaml.',
                     'name = ' + json.dumps(name), 'description = ' + json.dumps(desc),
                     'developer_instructions = ' + json.dumps(body, ensure_ascii=False)]
            if 'model' in selected:
                lines.append('model = ' + json.dumps(selected['model']))
            if 'effort' in selected:
                lines.append('model_reasoning_effort = ' + json.dumps(selected['effort']))
            # Session permission overrides may supersede this; no permission expansion.
            if role in ('architect', 'explorer', 'debugger', 'reviewer'):
                lines.append('sandbox_mode = "read-only"')
            content = '\n'.join(lines) + '\n'
            tomllib.loads(content)
            result[name + '.toml'] = content
        else:
            lines = ['---', 'name: ' + json.dumps(name), 'description: ' + json.dumps(desc),
                     'model: ' + json.dumps(selected.get('model', 'inherit')),
                     'disallowedTools: Agent']
            if role == 'reviewer':
                lines.append('tools: Read, Glob, Grep')
            content = '\n'.join(lines) + '\n---\n\n<!-- GENERATED FILE: edit core/agents or models.yaml. -->\n\n' + body + '\n'
            result[name + '.md'] = content
    return result


def capabilities(runtime):
    if runtime not in config.RUNTIMES:
        raise DevFlowError('Unknown runtime')
    return {'runtime': runtime, 'worker_launcher': 'native tools supplied by current session',
            'capability_availability': 'requires live session preflight; not inferred from installed binaries',
            'parallel_dispatch': False, 'git_helpers': True, 'coordinator_model_selection': False,
            'worker_effort_config': runtime == 'codex', 'model_availability': 'not_verified',
            'independent_review': 'requires distinct worker identity and actual native worker capability'}
