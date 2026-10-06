"""Persistent Coordinator-owned runs and revision-bound completion gates."""
import copy
import datetime as dt
import json
import math
import uuid
from pathlib import Path
from . import config
from .storage import DevFlowError, FileLock, atomic_write, json_bytes, now, read_json, safe_id

MODES = ('error', 'feature', 'optimize')
FINAL_STATES = ('completed', 'partial', 'blocked', 'cancelled')
RESULT_FIELDS = ('schema_version', 'run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                 'observed_revision', 'result_revision', 'workspace_dirty', 'criteria_results', 'findings',
                 'files_inspected', 'files_changed', 'commits', 'decisions', 'validation', 'risks',
                 'out_of_scope', 'questions', 'next_action')
LIST_FIELDS = ('criteria_results', 'findings', 'files_inspected', 'files_changed', 'commits',
               'decisions', 'validation', 'risks', 'out_of_scope', 'questions')


def run_dir(data, run_id):
    return Path(data) / 'runs' / safe_id(run_id)


class RunLock(FileLock):
    def __init__(self, data, run_id, owner):
        super().__init__(run_dir(data, run_id) / 'coordinator.lock', owner)


def create(data, repository, mode, request, model_config, branch, revision, criteria,
           workspace=None, runtime='codex', owner='coordinator', capabilities=None):
    if mode not in MODES or runtime not in config.RUNTIMES or not request.strip():
        raise DevFlowError('Run needs a valid mode/runtime and nonempty request')
    if not criteria or not all(isinstance(c, str) and c.strip() for c in criteria):
        raise DevFlowError('Define acceptance criteria before starting implementation')
    if len(set(criteria)) != len(criteria):
        raise DevFlowError('Acceptance criteria must be unique')
    run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:10]
    from .gitops import common_dir
    try:
        # Shared by every checkout of the repository; lets cleanup find runs from any linked worktree.
        identity = common_dir(repository)
    except DevFlowError:
        identity = None
    run = {'schema_version': 1, 'run_id': run_id, 'repository': str(Path(repository).resolve()),
           'git_common_dir': identity,
           'workspace': str(Path(workspace or repository).resolve()), 'mode': mode, 'request': request,
           'runtime': runtime, 'branch': branch, 'base_revision': revision, 'current_revision': revision,
           'coordinator_id': owner, 'created_at': now(), 'updated_at': now(), 'phase': 'preflight',
           'status': 'active', 'acceptance_criteria': list(criteria), 'criteria_results': [],
           'config_snapshot': copy.deepcopy(config.validate(model_config)), 'capabilities': capabilities or {},
           'tasks': [], 'workers': [], 'authors': [owner], 'validations': [], 'required_checks': [],
           'review_required': False, 'review': None, 'findings': [], 'attempts': {}, 'decisions': [],
           'questions': [], 'measurement': None, 'next_action': 'Inspect workflow and assign the next task',
           'events': []}
    save(data, run, 'created')
    return run


def load(data, run_id):
    value = read_json(run_dir(data, run_id) / 'state.json')
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('run_id') != run_id:
        raise DevFlowError('Run state schema/identity mismatch')
    return value


def save(data, run, event):
    safe_id(run['run_id'])
    config.validate(run['config_snapshot'])
    run['updated_at'] = now()
    run.setdefault('events', []).append({'at': run['updated_at'], 'event': event})
    folder = run_dir(data, run['run_id'])
    # State is authoritative; context/journal are projections and can be rebuilt on resume.
    atomic_write(folder / 'state.json', json_bytes(run))
    context = '# DevFlow context\n\n' + '\n'.join(f'{key}: {json.dumps(run[key], ensure_ascii=False)}'
        for key in ('request', 'mode', 'acceptance_criteria', 'workspace', 'branch', 'base_revision',
                    'current_revision', 'phase', 'status', 'decisions', 'tasks', 'questions', 'next_action'))
    atomic_write(folder / 'context.md', (context + '\n').encode('utf-8'))
    atomic_write(folder / 'events.jsonl', ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in run['events']).encode('utf-8'))


def require_owner(run, owner):
    if run.get('coordinator_id') != owner:
        raise DevFlowError('Coordinator identity mismatch; inspect workers and explicitly claim this run before mutation')


def status(data, run_id=None, repository=None, verify_git=True):
    if run_id:
        run = load(data, run_id)
    else:
        candidates, errors = [], []
        folder = Path(data) / 'runs'
        for state_file in sorted(folder.glob('*/state.json')) if folder.exists() else []:
            try:
                item = load(data, state_file.parent.name)
                if repository is None or Path(item['repository']).resolve() == Path(repository).resolve():
                    candidates.append(item)
            except DevFlowError as exc:
                errors.append(str(exc))
        if len(candidates) != 1:
            return {'candidates': [{'run_id': r['run_id'], 'mode': r['mode'], 'status': r['status'],
                                    'phase': r['phase'], 'updated_at': r['updated_at']} for r in candidates],
                    'errors': errors, 'message': 'No unique run; select --run or start a new task'}
        run = candidates[0]
    info = {'run': run, 'worker_activity': 'Recorded state only; live worker activity is not confirmed',
            'last_recorded_at': run['updated_at'], 'evidence_current': 'not_verified'}
    if verify_git:
        try:
            from .gitops import inspect
            live = inspect(run['workspace'])
            info['live_git'] = live
            candidate_matches = (not live['dirty'] and live['revision'] == run['current_revision']
                                 and live['branch'] == run['branch'])
            latest_checks, latest_criteria = {}, {}
            for check in run['validations']:
                latest_checks[check.get('name')] = check
            for criterion in run['criteria_results']:
                latest_criteria[criterion.get('criterion')] = criterion
            records = list(latest_checks.values()) + list(latest_criteria.values())
            if run.get('review'):
                records.append(run['review'])
            if run.get('measurement'):
                records.append({'revision': run['measurement'].get('after_revision')})
            info['candidate_matches_record'] = candidate_matches
            info['evidence_current'] = (candidate_matches and bool(records)
                                        and all(r.get('revision') == run['current_revision'] for r in records))
            info['evidence_note'] = ('Version freshness only; consult check outcomes and missing requirements. '
                                     'No evidence, older evidence or a changed candidate cannot be called current.')
        except DevFlowError as exc:
            info['git_verification_error'] = str(exc)
    return info


def make_task(run, role, objective, write_scope, read_scope=None, dependencies=None, task_id=None, correction_key=None):
    if role not in config.TASK_ROLES or not objective.strip():
        raise DevFlowError('Task needs a worker role and objective')
    for path in write_scope:
        scope_path(run['workspace'], path)
    task_id = task_id or 'task-' + uuid.uuid4().hex[:10]
    if role == 'fixer' and not correction_key:
        raise DevFlowError('Fixer needs an explicit stable correction_key or an inherited replacement key')
    correction_key = correction_key or task_id
    safe_id(correction_key)
    remaining = 3 - len(run['attempts'].get(correction_key, []))
    if remaining <= 0 and role == 'fixer':
        raise DevFlowError('Correction budget exhausted for this logical issue; preserve work and stop')
    return {'schema_version': 1, 'run_id': run['run_id'], 'task_id': task_id,
            'role': role, 'objective': objective, 'original_request': run['request'],
            'acceptance_criteria': run['acceptance_criteria'], 'dependencies': dependencies or [],
            'workspace': run['workspace'], 'branch': run['branch'], 'base_revision': run['base_revision'],
            'candidate_revision': run['current_revision'], 'read_scope': read_scope or [],
            'write_scope': write_scope, 'shared_contracts': [], 'relevant_context': [],
            'constraints': ['No delegation; deliver to Coordinator; no push or merge main/master'],
            'expected_validation': list(run['required_checks']), 'remaining_fix_cycles': max(0, remaining),
            'correction_key': correction_key,
            'deliver_to': 'coordinator', 'status': 'pending', 'result': None}


def scope_path(workspace, relative):
    if not isinstance(relative, str) or not relative or relative.startswith('-'):
        raise DevFlowError('Invalid scope path')
    relative = relative.replace('\\', '/')
    raw = Path(relative)
    if raw.is_absolute() or ':' in relative or '..' in raw.parts:
        raise DevFlowError('Scope paths must be relative and cannot traverse outside workspace')
    path = (Path(workspace) / raw).resolve()
    if not path.is_relative_to(Path(workspace).resolve()):
        raise DevFlowError('Scope path resolves outside workspace')
    return path


def allowed_change(task, relative):
    target = scope_path(task['workspace'], relative)
    for entry in task['write_scope']:
        allowed = scope_path(task['workspace'], entry)
        if target == allowed or (entry.endswith(('/', '\\')) and target.is_relative_to(allowed)):
            return True
    return False


def empty_result(task, worker_id):
    result = {field: [] for field in LIST_FIELDS}
    result.update({'schema_version': 1, 'run_id': task['run_id'], 'task_id': task['task_id'],
                   'worker_id': worker_id, 'role': task['role'], 'status': 'partial', 'summary': '',
                   'observed_revision': task['candidate_revision'], 'result_revision': None,
                   'workspace_dirty': False, 'next_action': ''})
    return result


def validate_result(task, result):
    if isinstance(result, dict):
        # Empty lists and next_action may be omitted; files_changed is still checked against Git.
        for field in LIST_FIELDS:
            result.setdefault(field, [])
        result.setdefault('next_action', '')
    if not isinstance(result, dict) or any(field not in result for field in RESULT_FIELDS):
        raise DevFlowError('Incomplete result contract; request missing fields before continuing')
    for field in ('run_id', 'task_id', 'role'):
        if result[field] != task[field]:
            raise DevFlowError(f'Result {field} does not match assignment')
    if result['schema_version'] != 1 or result['status'] not in ('done', 'partial', 'blocked', 'cancelled'):
        raise DevFlowError('Invalid result schema/status')
    if not isinstance(result['worker_id'], str) or not result['worker_id']:
        raise DevFlowError('Result needs the actual worker identity')
    if not isinstance(result['workspace_dirty'], bool) or any(not isinstance(result[f], list) for f in LIST_FIELDS):
        raise DevFlowError('Invalid result fields')
    if result['observed_revision'] != task['candidate_revision']:
        raise DevFlowError('Result observed a different candidate; reconcile before accepting')
    for changed in result['files_changed']:
        if not allowed_change(task, changed):
            raise DevFlowError(f'Worker changed a path outside write_scope: {changed}')
    if task['role'] == 'reviewer' and result['files_changed']:
        raise DevFlowError('Reviewer must not change product code/tests')
    for check in result['validation']:
        validate_check(check)
    for criterion in result['criteria_results']:
        validate_criterion(criterion)
        if criterion['criterion'] not in task['acceptance_criteria']:
            raise DevFlowError('Worker reported an unknown acceptance criterion')
    for finding in result['findings']:
        validate_finding(finding)
    return result


def validate_finding(finding):
    if not isinstance(finding, dict) or finding.get('kind') not in ('blocker', 'suggestion', 'out_of_scope'):
        raise DevFlowError('Findings need a valid classification')
    if finding.get('resolved') or 'resolution' in finding:
        raise DevFlowError('Resolve findings only through the evidence-bound resolve operation')
    if finding['kind'] == 'blocker' and any(not finding.get(f) for f in ('location', 'trigger', 'impact', 'evidence')):
        raise DevFlowError('Blocker needs location, trigger, impact and evidence')
    if 'id' in finding:
        safe_id(finding['id'])


def append_findings(run, findings):
    existing = {f.get('id') for f in run['findings'] if f.get('id')}
    for finding in findings:
        validate_finding(finding)
        value = copy.deepcopy(finding)
        value.setdefault('id', 'finding-' + uuid.uuid4().hex[:12])
        if value['id'] in existing:
            raise DevFlowError('Finding identity already exists')
        existing.add(value['id'])
        run['findings'].append(value)


def resolve_finding(run, value):
    if (not isinstance(value, dict) or set(value) != {'finding_id', 'revision', 'evidence', 'check'}
            or any(not isinstance(v, str) or not v.strip() for v in value.values())):
        raise DevFlowError('Resolution needs finding_id, current revision, evidence and a passing check')
    if value['revision'] != run['current_revision']:
        raise DevFlowError('Resolution must reference the current candidate')
    checks = [c for c in run['validations'] if c.get('name') == value['check']]
    if not checks or checks[-1].get('status') != 'passed' or checks[-1].get('revision') != value['revision']:
        raise DevFlowError('Resolution requires a passing current validation')
    validate_check(checks[-1])
    finding = next((f for f in run['findings'] if f.get('id') == value['finding_id']), None)
    if finding is None:
        raise DevFlowError('Unknown finding identity')
    finding.setdefault('resolution_history', []).append(copy.deepcopy(value))
    finding['resolved'] = True
    finding['resolution'] = copy.deepcopy(value)


def validate_check(check):
    if not isinstance(check, dict) or not check.get('name') or check.get('status') not in ('passed', 'failed', 'not_run', 'not_applicable'):
        raise DevFlowError('Invalid validation record')
    if not check.get('revision') or not check.get('procedure') or not check.get('evidence'):
        raise DevFlowError('Validation needs revision, procedure and evidence/reason')
    return check


def validate_criterion(value):
    if (not isinstance(value, dict) or not isinstance(value.get('criterion'), str)
            or not value['criterion'].strip() or value.get('status') not in ('passed', 'failed', 'not_run')
            or not isinstance(value.get('revision'), str) or not value['revision'].strip()
            or not isinstance(value.get('evidence'), str) or not value['evidence'].strip()):
        raise DevFlowError('Criterion result requires name, status, revision and concrete evidence/reason')
    return value


def record_attempt(run, task_id, failure, evidence):
    if not failure or not evidence:
        raise DevFlowError('Correction attempts need failure and evidence')
    history = run['attempts'].setdefault(task_id, [])
    if len(history) >= 3:
        raise DevFlowError('Three correction cycles exhausted; preserve work and return partial/blocked')
    if history and history[-1]['failure'] == failure and history[-1]['evidence'] == evidence:
        raise DevFlowError('Repeated failure without new evidence; stop recovery')
    history.append({'failure': failure, 'evidence': evidence, 'at': now()})


def assert_complete(run):
    if run.get('executor') == 'orca':
        from . import orca
        orca.assert_complete(run)
    revision = run['current_revision']
    if not revision or run.get('workspace_dirty', False):
        raise DevFlowError('Completion requires an identified clean candidate revision')
    for criterion in run['acceptance_criteria']:
        items = [c for c in run['criteria_results'] if c.get('criterion') == criterion]
        if not items or items[-1].get('status') != 'passed' or items[-1].get('revision') != revision:
            raise DevFlowError(f'Acceptance criterion lacks current passing evidence: {criterion}')
        validate_criterion(items[-1])
    if any(t.get('status') != 'done' for t in run['tasks']):
        raise DevFlowError('Some assignments are unfinished')
    if any(w.get('status') not in ('done', 'cancelled_confirmed') for w in run['workers']):
        raise DevFlowError('Some workers are still active or their cancellation is unconfirmed')
    if any(f.get('kind') == 'blocker' and (not f.get('resolved', False)
           or f.get('resolution', {}).get('revision') != revision) for f in run['findings']):
        raise DevFlowError('Unresolved review blockers remain')
    for finding in run['findings']:
        if finding.get('kind') == 'blocker':
            resolution = finding.get('resolution') or {}
            checks = [c for c in run['validations'] if c.get('name') == resolution.get('check')]
            if not resolution.get('evidence') or not checks or checks[-1].get('status') != 'passed' or checks[-1].get('revision') != revision:
                raise DevFlowError('Blocker resolution lacks current passing validation')
            validate_check(checks[-1])
    for name in run['required_checks']:
        items = [c for c in run['validations'] if c.get('name') == name]
        if not items or items[-1].get('revision') != revision or items[-1].get('status') not in ('passed', 'not_applicable'):
            raise DevFlowError(f'Required check lacks current evidence: {name}')
        validate_check(items[-1])
    if run['review_required']:
        review = run.get('review') or {}
        if (review.get('verdict') != 'passed' or review.get('revision') != revision
                or not review.get('worker_id') or review['worker_id'] in run['authors']
                or review['worker_id'] == run['coordinator_id']):
            raise DevFlowError('Current independent review is required; preserve as partial if unavailable')
    if run['mode'] == 'optimize':
        measurement = run.get('measurement') or {}
        if not measurement.get('metric') or not measurement.get('procedure') or not measurement.get('evidence'):
            raise DevFlowError('Optimization lacks objective measurement evidence')
        before, after = measurement.get('before'), measurement.get('after')
        if (type(before) not in (int, float) or type(after) not in (int, float)
                or not math.isfinite(before) or not math.isfinite(after)
                or measurement.get('after_revision') != revision
                or not measurement.get('before_revision')):
            raise DevFlowError('Optimization needs comparable finite measurements tied to revisions')
        direction = measurement.get('direction')
        if not ((direction == 'lower' and after < before) or (direction == 'higher' and after > before)):
            raise DevFlowError('Objective improvement is not demonstrated')
