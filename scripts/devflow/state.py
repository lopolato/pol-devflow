"""Persistent Coordinator-owned runs and revision-bound completion gates."""
import copy
import datetime as dt
import json
import math
import re
import uuid
from pathlib import Path
from . import config
from .storage import DevFlowError, FileLock, atomic_write, json_bytes, now, read_json, safe_id

MODES = ('error', 'feature', 'optimize')
FINAL_STATES = ('completed', 'partial', 'blocked', 'cancelled')
RESULT_STATUSES = ('done', 'partial', 'blocked', 'cancelled')
RESULT_FIELDS = ('schema_version', 'run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                 'observed_revision', 'result_revision', 'workspace_dirty', 'criteria_results', 'findings',
                 'files_inspected', 'files_changed', 'commits', 'decisions', 'validation', 'risks',
                 'out_of_scope', 'questions', 'next_action')
INCIDENT_STATUSES = ('resolved', 'not_verified', 'different_cause', 'accepted_unverified')
CODE_MAP_LIMIT = 50
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
           'questions': [], 'measurement': None, 'incident': None, 'next_action': 'Inspect workflow and assign the next task',
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
    if event == 'close' and run.get('status') in FINAL_STATES:
        # Settlement/accounting may update updated_at later; the closure endpoint must stay stable.
        run['closed_at'] = run['updated_at']
    run.setdefault('events', []).append({'at': run['updated_at'], 'event': event})
    folder = run_dir(data, run['run_id'])
    # State is authoritative; context/journal are projections and can be rebuilt on resume.
    atomic_write(folder / 'state.json', json_bytes(run))
    context = '# DevFlow context\n\n' + '\n'.join(f'{key}: {json.dumps(run.get(key), ensure_ascii=False)}'
        for key in ('request', 'mode', 'acceptance_criteria', 'workspace', 'branch', 'base_revision',
                    'current_revision', 'phase', 'status', 'incident', 'decisions', 'tasks', 'questions',
                    'next_action'))
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
            'last_recorded_at': run['updated_at'], 'evidence_current': 'not_verified',
            'overdue_tasks': overdue_tasks(run), 'timing': elapsed_timing(run)}
    if run.get('nesting'):
        info['delegation_tree'] = delegation_tree(run)
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


def delegation_tree(run):
    tasks = run.get('tasks', [])
    def node(task):
        return {'task_id': task['task_id'], 'role': task['role'], 'status': task.get('status'),
                'depth': task.get('depth', 1), 'children': [node(child) for child in tasks
                    if child.get('parent_task_id') == task['task_id']]}
    return {'max_workers': (run.get('nesting') or {}).get('max_workers'),
            'roots': [node(task) for task in tasks if task.get('delegation', {}).get('enabled')
                      and not task.get('parent_task_id')]}


def elapsed_timing(run, at=None):
    """Observed wall-clock intervals, never agent compute or a claim of runtime activity."""
    at = at or dt.datetime.now(dt.timezone.utc)
    def parse(value):
        try:
            stamp = dt.datetime.fromisoformat(value)
            return stamp if stamp.tzinfo else None
        except (TypeError, ValueError):
            return None
    def interval(start, end):
        start, end = parse(start), parse(end)
        return round((end - start).total_seconds(), 3) if start and end and end >= start else None
    closed = run.get('status') in FINAL_STATES
    endpoint = at.isoformat()
    endpoint_source = 'observation_now'
    if closed:
        endpoint = run.get('closed_at')
        endpoint_source = 'closed_at'
        if not parse(endpoint):
            # Legacy runs recorded explicit close events; generic updates are not evidence of closure.
            endpoint = next((event.get('at') for event in reversed(run.get('events', []))
                             if event.get('event') == 'close' and parse(event.get('at'))), None)
            endpoint_source = 'close_event' if endpoint else 'unknown'
    tasks = []
    for task in run.get('tasks', []):
        recorded = task.get('result_recorded_at')
        # Old records have no per-task delivery timestamp; do not infer one from an unrelated event.
        end = recorded or (endpoint if task.get('status') in ('pending', 'active') else None)
        tasks.append({'task_id': task.get('task_id'), 'role': task.get('role'),
                      'assigned_at': task.get('assigned_at'), 'result_recorded_at': recorded,
                      'elapsed_seconds': interval(task.get('assigned_at'), end)})
    return {'elapsed_seconds': interval(run.get('created_at'), endpoint), 'tasks': tasks,
            'observation_ended_at': endpoint, 'endpoint_source': endpoint_source,
            'note': 'Observed wall-clock elapsed time includes waiting, coordination and checks; '
                    'not agent compute. Overlapping tasks are not additive; missing timestamps stay null.'}


def overdue_tasks(run, at=None):
    """Pending/active assignments past their recorded budget; read-only, never changes the run."""
    at, result = at or dt.datetime.now(dt.timezone.utc), []
    for task in run.get('tasks', []):
        budget = task.get('budget_minutes')
        if task.get('status') not in ('pending', 'active') or not budget or not task.get('assigned_at'):
            continue
        try:
            elapsed = (at - dt.datetime.fromisoformat(task['assigned_at'])).total_seconds() / 60
        except (TypeError, ValueError):
            continue
        if elapsed > budget:
            result.append({'task_id': task['task_id'], 'role': task['role'],
                           'minutes_elapsed': round(elapsed, 1), 'budget_minutes': budget})
    return result


def validate_incident(value):
    if not isinstance(value, dict) or set(value) - {'symptom', 'status', 'evidence', 'accepted_by'}:
        raise DevFlowError('Incident accepts only symptom, status, evidence and accepted_by')
    if value.get('status') not in INCIDENT_STATUSES:
        raise DevFlowError('Incident status must be one of ' + ', '.join(INCIDENT_STATUSES))
    for key in ('symptom', 'evidence'):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise DevFlowError(f'Incident needs a nonempty {key}')
    accepted = value.get('accepted_by')
    if value['status'] == 'accepted_unverified' and accepted is None:
        raise DevFlowError('accepted_unverified needs accepted_by (who accepted the unverified incident)')
    if accepted is not None and (not isinstance(accepted, str) or not accepted.strip()):
        raise DevFlowError('accepted_by must be a nonempty string')
    return value


def record_incident(run, value):
    validate_incident(value)
    if run.get('incident'):
        # Replaced values stay visible for audit.
        run.setdefault('incident_history', []).append(run['incident'])
    run['incident'] = copy.deepcopy(value) | {'recorded_at': now()}
    return run['incident']


def make_task(run, role, objective, write_scope, read_scope=None, dependencies=None, task_id=None, correction_key=None,
              budget_minutes=None, parent_task_id=None, delegation=None, depth=1):
    if role not in config.TASK_ROLES or not objective.strip():
        raise DevFlowError('Task needs a worker role and objective')
    if budget_minutes is not None and (type(budget_minutes) is not int or budget_minutes <= 0):
        raise DevFlowError('--budget-minutes must be a positive integer')
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
    task = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': task_id,
            'role': role, 'objective': objective, 'original_request': run['request'],
            'acceptance_criteria': run['acceptance_criteria'], 'dependencies': dependencies or [],
            'workspace': run['workspace'], 'branch': run['branch'], 'base_revision': run['base_revision'],
            'candidate_revision': run['current_revision'], 'read_scope': read_scope or [],
            'write_scope': write_scope, 'shared_contracts': [], 'relevant_context': [],
            'constraints': ['Deliver to Coordinator; no push or merge main/master'],
            'expected_validation': list(run['required_checks']), 'remaining_fix_cycles': max(0, remaining),
            'correction_key': correction_key, 'assigned_at': now(), 'budget_minutes': budget_minutes,
            'deliver_to': 'coordinator', 'status': 'pending', 'result': None,
            'parent_task_id': parent_task_id, 'depth': depth,
            'delegation': copy.deepcopy(delegation or {'enabled': False})}
    if task['delegation'].get('enabled'):
        task['constraints'].append('You may request read-only explorer/debugger/tester child tasks through the Coordinator; do not edit shared run state')
    else:
        task['constraints'].append('Do not delegate; deliver your result to the Coordinator')
    return task


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
        missing = [field for field in RESULT_FIELDS if not isinstance(result, dict) or field not in result]
        raise DevFlowError('Incomplete result contract; missing fields: ' + ', '.join(missing))
    for field in ('run_id', 'task_id', 'role'):
        if result[field] != task[field]:
            raise DevFlowError(f'Result {field} does not match assignment')
    if result['schema_version'] != 1:
        raise DevFlowError('schema_version must be 1')
    if result['status'] not in RESULT_STATUSES:
        raise DevFlowError('status must be one of: ' + ', '.join(RESULT_STATUSES))
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
    if task.get('parent_task_id') and 'review' in result:
        raise DevFlowError('A helper cannot issue the independent review verdict')
    for index, check in enumerate(result['validation']):
        try:
            validate_check(check)
        except DevFlowError as exc:
            raise DevFlowError(f'validation[{index}]: {exc}') from exc
    for index, criterion in enumerate(result['criteria_results']):
        try:
            validate_criterion(criterion)
        except DevFlowError as exc:
            raise DevFlowError(f'criteria_results[{index}]: {exc}') from exc
        if criterion['criterion'] not in task['acceptance_criteria']:
            raise DevFlowError('Worker reported an unknown acceptance criterion')
    for finding in result['findings']:
        validate_finding(finding)
    if 'code_map' in result:
        validate_code_map(task['workspace'], result['code_map'])
    if 'subdelegation_trace' in result:
        trace = result['subdelegation_trace']
        if not task.get('delegation', {}).get('enabled'):
            raise DevFlowError('Only a task with an explicit delegation grant may report subdelegation_trace')
        if (not isinstance(trace, dict) or set(trace) != {'child_task_ids', 'summary'}
                or not isinstance(trace['child_task_ids'], list)
                or not all(isinstance(item, str) and item for item in trace['child_task_ids'])
                or not isinstance(trace['summary'], str) or not trace['summary'].strip()):
            raise DevFlowError('subdelegation_trace needs child_task_ids and a nonempty summary')
        if len(set(trace['child_task_ids'])) != len(trace['child_task_ids']):
            raise DevFlowError('subdelegation_trace child_task_ids must be unique')
    return result


def validate_code_map(workspace, entries):
    """Optional handoff of where the relevant code lives, so the next worker can skip rediscovery."""
    if not isinstance(entries, list) or len(entries) > CODE_MAP_LIMIT:
        raise DevFlowError(f'code_map must be a list of at most {CODE_MAP_LIMIT} entries')
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {'path', 'symbol', 'lines', 'why'}:
            raise DevFlowError('code_map entries accept only path, symbol, lines and why')
        scope_path(workspace, entry.get('path'))
        if any(entry.get(k) is not None and not isinstance(entry[k], str) for k in ('symbol', 'lines', 'why')):
            raise DevFlowError('code_map symbol, lines and why must be strings')
        lines = entry.get('lines')
        match = re.fullmatch(r'(\d+)(?:-(\d+))?', lines) if lines is not None else None
        if lines is not None and (not match or int(match[1]) < 1 or (match[2] and int(match[2]) < int(match[1]))):
            raise DevFlowError('code_map lines must look like "12" or "10-40"')
    return entries


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
        raise DevFlowError('Validation needs name and status (passed, failed, not_run, not_applicable)')
    if not check.get('revision') or not check.get('procedure') or not check.get('evidence'):
        raise DevFlowError('Validation needs revision, procedure and evidence/reason')
    return check


def validate_criterion(value):
    if (not isinstance(value, dict) or not isinstance(value.get('criterion'), str)
            or not value['criterion'].strip() or value.get('status') not in ('passed', 'failed', 'not_run')
            or not isinstance(value.get('revision'), str) or not value['revision'].strip()
            or not isinstance(value.get('evidence'), str) or not value['evidence'].strip()):
        raise DevFlowError('Criterion result requires criterion, status (passed, failed, not_run), revision and concrete evidence/reason')
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


def completion_blockers(run):
    """Every reason the run cannot be completed now (empty list when it can)."""
    blockers = []

    from . import nesting
    for task in run.get('tasks', []):
        blockers.extend(nesting.task_blockers(run, task))

    def valid(check, value):
        try:
            check(value)
        except DevFlowError as exc:
            blockers.append(str(exc))

    if run.get('executor') == 'orca':
        from . import orca
        valid(orca.assert_complete, run)
    revision = run['current_revision']
    if not revision or run.get('workspace_dirty', False):
        blockers.append('Completion requires an identified clean candidate revision')
    for criterion in run['acceptance_criteria']:
        items = [c for c in run['criteria_results'] if c.get('criterion') == criterion]
        if not items or items[-1].get('status') != 'passed' or items[-1].get('revision') != revision:
            blockers.append(f'Acceptance criterion lacks current passing evidence: {criterion}')
        else:
            valid(validate_criterion, items[-1])
    unfinished = [t for t in run['tasks'] if t.get('status') != 'done']
    if unfinished:
        blockers.append('Some assignments are unfinished: ' + ', '.join(
            f"{t.get('task_id')} ({t.get('role')}, {t.get('status')})" for t in unfinished)
            + '; record their results or assign a replacement with --replaces')
    workers = [w for w in run['workers'] if w.get('status') not in ('done', 'cancelled_confirmed')]
    if workers:
        blockers.append('Some workers are still active or their cancellation is unconfirmed: ' + ', '.join(
            f"{w.get('worker_id')} ({w.get('status')})" for w in workers))
    current = []
    for finding in run['findings']:
        if finding.get('kind') != 'blocker':
            continue
        if not finding.get('resolved', False) or finding.get('resolution', {}).get('revision') != revision:
            blockers.append('Unresolved review blockers remain' + (f": {finding['id']}" if finding.get('id') else ''))
        else:
            current.append(finding)
    for finding in current:
        resolution = finding.get('resolution') or {}
        checks = [c for c in run['validations'] if c.get('name') == resolution.get('check')]
        if not resolution.get('evidence') or not checks or checks[-1].get('status') != 'passed' or checks[-1].get('revision') != revision:
            blockers.append('Blocker resolution lacks current passing validation')
        else:
            valid(validate_check, checks[-1])
    for name in run['required_checks']:
        items = [c for c in run['validations'] if c.get('name') == name]
        if not items or items[-1].get('revision') != revision or items[-1].get('status') not in ('passed', 'not_applicable'):
            blockers.append(f'Required check lacks current evidence: {name}')
        else:
            valid(validate_check, items[-1])
    if run['review_required']:
        review = run.get('review') or {}
        if (review.get('verdict') != 'passed' or review.get('revision') != revision
                or not review.get('worker_id') or review['worker_id'] in run['authors']
                or review['worker_id'] == run['coordinator_id']):
            blockers.append('Current independent review is required; preserve as partial if unavailable')
    if run['mode'] == 'optimize':
        measurement = run.get('measurement') or {}
        before, after, direction = measurement.get('before'), measurement.get('after'), measurement.get('direction')
        if not measurement.get('metric') or not measurement.get('procedure') or not measurement.get('evidence'):
            blockers.append('Optimization lacks objective measurement evidence')
        elif (type(before) not in (int, float) or type(after) not in (int, float)
                or not math.isfinite(before) or not math.isfinite(after)
                or measurement.get('after_revision') != revision
                or not measurement.get('before_revision')):
            blockers.append('Optimization needs comparable finite measurements tied to revisions')
        elif not ((direction == 'lower' and after < before) or (direction == 'higher' and after > before)):
            blockers.append('Objective improvement is not demonstrated')
    if run['mode'] == 'error':
        incident = run.get('incident') or {}
        if incident.get('status') not in ('resolved', 'accepted_unverified'):
            blockers.append('Reported incident not verified as resolved; record incident status resolved with '
                            'evidence, or accepted_unverified with accepted_by, through _run update '
                            f"(current: {incident.get('status') or 'missing'})")
    return blockers


def assert_complete(run):
    blockers = completion_blockers(run)
    if blockers:
        raise DevFlowError('; '.join(blockers))
