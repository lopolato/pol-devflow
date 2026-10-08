"""Evidence bridge to Orca. Never launches processes or claims runtime authority."""
import copy
import json
from pathlib import Path
from . import adapters, config, state
from .storage import DevFlowError, now

READ_ROLES = ('architect', 'explorer', 'debugger', 'reviewer', 'tester')


def read_task(task):
    return task['role'] in READ_ROLES and not task['write_scope']


def check_assignment(run, role, write_scope):
    active = [t for t in run['tasks'] if t['status'] in ('pending', 'active')]
    if not active:
        return
    # Read-only tasks on the same clean revision may run as a wave (native or Orca); writers stay sequential.
    if (role not in READ_ROLES or write_scope
            or any(not read_task(t) or t['candidate_revision'] != run['current_revision'] for t in active)):
        raise DevFlowError('Pending assignments: only independent read-only tasks may share a wave')


def text_fields(value, names):
    if not isinstance(value, dict):
        raise DevFlowError('Orca evidence must be an object')
    for name in names:
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise DevFlowError('Orca evidence needs ' + name)


def link(run, task, value):
    text_fields(value, ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id',
                        'workspace', 'runtime', 'evidence'))
    if set(value) & {'settlement', 'accounting', 'settled_at', 'linked_at'}:
        raise DevFlowError('Link cannot inject settlement/accounting or bridge timestamps')
    if value['runtime'] not in config.RUNTIMES or Path(value['workspace']).resolve() != Path(task['workspace']).resolve():
        raise DevFlowError('Orca worker must use the assigned runtime/workspace')
    if task.get('orca') or task.get('result') is not None:
        raise DevFlowError('Assignment already bound/recorded; inspect instead of overwriting a Dispatch')
    if run.get('orca_run_id') and run['orca_run_id'] != value['orca_run_id']:
        raise DevFlowError('Orca Run differs from the bound Run')
    if any(t.get('orca', {}).get('dispatch_id') == value['dispatch_id'] for t in run['tasks']):
        raise DevFlowError('Orca Dispatch already bound to another assignment')
    handle = value.get('agent_handle')
    if not isinstance(handle, str) or not handle or value['worker_id'] != 'orca:' + handle:
        raise DevFlowError('worker_id must be orca: plus the proven stable agent_handle')
    prior = [t for t in run['tasks'] if t.get('orca', {}).get('orca_task_id') == value['orca_task_id']]
    if prior:
        previous = prior[-1]
        if (task.get('replaces') != previous['task_id']
                or previous['orca'].get('settlement', {}).get('outcome') != 'failed'):
            raise DevFlowError('Reuse an Orca Task only for an explicit replacement of its latest failed attempt')
    for previous in run['tasks']:
        binding = previous.get('orca') or {}
        if binding.get('agent_handle') == handle and not binding.get('settlement'):
            raise DevFlowError('Settle the previous Dispatch before reusing its agent')
    run['orca_run_id'] = value['orca_run_id']
    task['orca'] = copy.deepcopy(value) | {'linked_at': now()}
    task['status'] = 'active'
    return task['orca']


def settle(task, value):
    binding = task.get('orca')
    if not binding:
        raise DevFlowError('Assignment has no bound Orca Dispatch')
    text_fields(value, ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id', 'type', 'outcome', 'evidence'))
    if any(value[k] != binding[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')):
        raise DevFlowError('Orca completion does not match the active Dispatch/worker')
    normal = value['type'] == 'worker_done' and value['outcome'] in ('succeeded', 'failed')
    recovery = (value['type'] == 'runtime_settled' and value['outcome'] == 'failed'
                and value.get('proof') in ('failed', 'stopped', 'abandoned', 'start_failed'))
    if not (normal or recovery):
        raise DevFlowError('Settlement requires accepted worker_done or positively confirmed runtime settlement')
    if binding.get('settlement') and binding['settlement'] != value:
        raise DevFlowError('Conflicting completion; preserve the accepted settlement')
    binding['settlement'] = copy.deepcopy(value)
    binding.setdefault('settled_at', now())
    return binding


def validate_result(task, result):
    binding = task.get('orca') or {}
    settlement = binding.get('settlement') or {}
    if not settlement or result['worker_id'] != binding.get('worker_id'):
        raise DevFlowError('Orca result requires accepted matching settlement and stable worker identity')
    expected = 'succeeded' if result['status'] == 'done' else 'failed'
    if settlement['outcome'] != expected:
        raise DevFlowError('Result status contradicts the explicit Orca outcome')


def account(run, task, value):
    binding = task.get('orca') or {}
    if not binding.get('settlement'):
        raise DevFlowError('Only accepted settlement authorizes accounting')
    text_fields(value, ('dispatch_id', 'action', 'evidence'))
    if value['dispatch_id'] != binding['dispatch_id'] or value['action'] not in ('released', 'reused', 'retained'):
        raise DevFlowError('Accounting must name the bound Dispatch and a valid next owner')
    if value['action'] == 'retained' and value.get('user_requested') is not True:
        receipt = value.get('orca_release_result')
        runtime_retention = (
            value.get('retention_source') == 'orca'
            and isinstance(receipt, dict)
            and receipt.get('dispatchId') == binding['dispatch_id']
            and receipt.get('state') == 'retained'
            and receipt.get('reason') == 'user_takeover'
            and receipt.get('processAction') == 'none'
        )
        if not runtime_retention:
            raise DevFlowError('Retention requires an explicit user request or a matching Orca user_takeover receipt')
    if value['action'] == 'reused':
        following_task = next((t for t in run['tasks']
                          if t.get('orca', {}).get('dispatch_id') == value.get('next_dispatch_id')), None)
        following = following_task.get('orca') if following_task else None
        if (not following or following is binding
                or following['agent_handle'] != binding['agent_handle']
                or run['tasks'].index(following_task) <= run['tasks'].index(task)
                or following['linked_at'] < binding['settled_at']):
            raise DevFlowError('Reuse requires a bound follow-up Dispatch on the same proven agent')
    if binding.get('accounting') and binding['accounting'] != value:
        raise DevFlowError('Accounting already recorded; inspect instead of replacing it')
    binding['accounting'] = copy.deepcopy(value)
    return binding


def assert_complete(run):
    for task in run['tasks']:
        binding = task.get('orca') or {}
        if not binding.get('settlement') or not binding.get('accounting'):
            raise DevFlowError('Orca assignment lacks accepted settlement or terminal accounting')


def snapshot_settings(data, selected):
    """Respect explicit settings; capture existing managed role choices when inherited."""
    from . import package
    from .storage import digest
    import re
    import tomllib
    snapshot = copy.deepcopy(selected)
    for runtime in config.RUNTIMES:
        manifest = package.load_manifest(data, runtime)
        if not manifest:
            continue
        for role in config.WORKER_ROLES:
            if snapshot['profiles'][role][runtime]:
                continue
            relative = f'agents/pol-{role}.' + ('toml' if runtime == 'codex' else 'md')
            path = package.managed_path(manifest['runtime_home'], relative, runtime)
            expected = manifest['files'].get(relative)
            if not expected or not path.is_file() or digest(path.read_bytes()) != expected:
                raise DevFlowError('Managed model profile changed/missing; reconcile before Orca launch: ' + str(path))
            native = path.read_text(encoding='utf-8')
            if runtime == 'codex':
                value = tomllib.loads(native)
                settings = {'model': value['model']} if 'model' in value else {}
                if settings and 'model_reasoning_effort' in value:
                    settings['effort'] = value['model_reasoning_effort']
            else:
                match = re.search(r'(?m)^model: (.+)$', native.split('---\n', 2)[1])
                model = json.loads(match.group(1)) if match else 'inherit'
                settings = {'model': model} if model != 'inherit' else {}
            snapshot['profiles'][role][runtime] = settings
    return config.validate(snapshot)


def spec(run, task, root, runtime=None):
    runtime = runtime or run['runtime']
    if runtime not in config.RUNTIMES:
        raise DevFlowError('Unsupported Orca agent runtime')
    rule = ('Context7: identify the installed library version before resolving an API doubt; reuse relevant '
            'verified extracts from relevant_context. Query only when needed and available; otherwise use '
            'official version-matched docs/local evidence. A latest-only response does not prove compatibility. '
            'Do not install MCPs or add Engram. Full policy if needed: ' +
            str((Path(root) / 'core/rules/technical-context.md').resolve()))
    body = adapters.instructions(task['role'], root)
    skeleton = state.empty_result(task, task.get('orca', {}).get('worker_id', 'orca:<proven stable agent_handle>'))
    if task['role'] == 'reviewer':
        skeleton['review'] = {'verdict': 'incomplete'}
    contract = ('Result enums: status=done|partial|blocked|cancelled; '
                'criteria_results[].status=passed|failed|not_run; '
                'validation[].status=passed|failed|not_run|not_applicable; '
                'review.verdict=passed|changes_required|incomplete. Do not invent synonyms. '
                'Retain every blocker and unsuccessful check; do not change evidence to make validation pass.\n'
                'When report files are permitted, preflight before worker_done: '
                f'python "{Path(root) / "scripts/devflow.py"}" _run validate-result '
                f'--run {run["run_id"]} --input <result.json> '
                '(preserve the Coordinator supplied --data-dir if nondefault). '
                'This checks schema/assignment only, not acceptance or runtime settlement. '
                'If report files are forbidden/unavailable, return the JSON for Coordinator preflight.\n'
                'Start with this skeleton; fill facts and actual worker identity, never assume success:\n'
                + json.dumps(skeleton, ensure_ascii=False, indent=2))
    identity = ('\nworker_id: ' + task['orca']['worker_id']) if task.get('orca') else ''
    text = ('DevFlow assignment executed through Orca. Target: workspace/read_scope/write_scope; '
            'Change: objective; Ownership: assigned role and write_scope; Constraints: contracts below; '
            'Observable acceptance: acceptance_criteria and expected_validation.\n'
            'The live Orca preamble owns lifecycle IDs.\n'
            'Follow its ask/check/heartbeat instructions. Send worker_done exactly once with explicit outcome, '
            'then end the turn. Do not delegate. Runtime IDs differ from DevFlow evidence IDs.\n'
            'Use worker_id orca:<proven stable agent_handle>, confirmed by Coordinator from the receipt. '
            'Ask the Coordinator if that handle is not supplied or exposed by the live preamble.\n'
            'Return the full structured result to Coordinator; write a report-path only if actually available '
            'and permitted. succeeded corresponds to result done; partial/blocked/cancelled require failed.\n'
            + identity + '\n\n' + json.dumps(task, ensure_ascii=False, indent=2) + '\n\n' + contract
            + '\n\n' + body + '\n\n' + rule)
    preferences = copy.deepcopy(run['config_snapshot']['profiles'][task['role']][runtime])
    if 'model' not in preferences:
        preferences.pop('effort', None)
    return {'spec': text, 'runtime': runtime,
            'launch_preferences': preferences,
            'workspace': task['workspace'], 'runtime_authority': 'Orca active Dispatch',
            'next_action': ('Inspect the already bound Dispatch; do not launch another worker' if task.get('orca')
                            else 'Coordinator launches through the version-matched Orca guide, verifies placement/effective model, then links the receipt')}
