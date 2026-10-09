"""Opt-in native worker nesting policy and assignment validation."""
from pathlib import Path

from .storage import DevFlowError

PARENT_ROLES = frozenset(('architect', 'reviewer', 'tester'))
LEAF_ROLES = frozenset(('explorer', 'debugger', 'tester'))
MAX_DEPTH = 2
MAX_CHILDREN_PER_PARENT = 2
MAX_GLOBAL_WORKERS = 4


def _check_capacity(run, limit, replacement=None):
    reservations = {('task', t['task_id']) for t in run.get('tasks', [])
                    if t.get('status') in ('pending', 'active') and t['task_id'] != replacement}
    for index, worker in enumerate(run.get('workers', [])):
        if worker.get('status') not in ('done', 'cancelled_confirmed'):
            key = ('task', worker['task_id']) if worker.get('task_id') else ('worker', worker.get('worker_id', index))
            reservations.add(key)
    if len(reservations) >= limit:
        raise DevFlowError('Native worker reservation limit reached')


def _directory(scope):
    return scope.endswith(('/', '\\'))


def _safe_scope(workspace, scope):
    if not isinstance(scope, str) or not scope.strip() or scope.startswith('-'):
        raise DevFlowError('Read scopes must be explicit relative paths')
    normalized = scope.replace('\\', '/')
    raw = Path(normalized)
    base = Path(workspace).resolve()
    if raw.is_absolute() or ':' in normalized or '..' in raw.parts:
        raise DevFlowError('Read scopes must be relative and cannot traverse outside workspace')
    resolved = (base / raw).resolve()
    if not resolved.is_relative_to(base):
        raise DevFlowError('Read scope resolves outside workspace')
    return resolved


def scope_contains(parent_workspace, parent_scope, child_workspace, child_scope):
    """Whether one explicit read scope is wholly inside another."""
    if Path(parent_workspace).resolve() != Path(child_workspace).resolve():
        return False
    base = Path(parent_workspace).resolve()
    parent = _safe_scope(parent_workspace, parent_scope)
    child = _safe_scope(child_workspace, child_scope)
    if child == parent:
        return not _directory(child_scope) or _directory(parent_scope)
    return _directory(parent_scope) and child.is_relative_to(parent)


def validate_assignment(run, role, write_scope, read_scope, can_delegate=False,
                        parent_task_id=None, native_evidence=None, native_max_workers=None,
                        replacement=None):
    """Validate opt-in tree topology before a task is appended to state."""
    nesting_flags = can_delegate or parent_task_id is not None or native_evidence is not None or native_max_workers is not None
    if not nesting_flags:
        if run.get('executor') == 'orca' and run.get('nesting'):
            raise DevFlowError('Nested tasks require the native executor')
        if run.get('nesting'):
            _check_capacity(run, run['nesting']['max_workers'], replacement)
        return None
    if run.get('executor') == 'orca':
        raise DevFlowError('Nesting flags are unavailable with executor Orca')
    if run.get('mode') == 'lite':
        raise DevFlowError('Nested tasks are available only in full workflows')

    known = {t['task_id']: t for t in run.get('tasks', [])}
    if parent_task_id is not None:
        if can_delegate or native_evidence is not None or native_max_workers is not None:
            raise DevFlowError('A child task cannot grant or redeclare delegation capability')
        parent = known.get(parent_task_id)
        if not parent or parent.get('status') not in ('pending', 'active'):
            raise DevFlowError('Parent task must be recorded and still active')
        grant = parent.get('delegation') or {}
        if not grant.get('enabled'):
            raise DevFlowError('Parent task has no explicit delegation grant')
        if parent.get('depth', 1) >= MAX_DEPTH:
            raise DevFlowError('Nested workers cannot delegate to a third level')
        if parent.get('write_scope'):
            raise DevFlowError('A parent that can delegate must have an empty write_scope')
        if role not in LEAF_ROLES or write_scope:
            raise DevFlowError('Child workers must be read-only explorer, debugger or tester tasks')
        if not read_scope:
            raise DevFlowError('Child tasks need an explicit nonempty read_scope')
        limit = (run.get('nesting') or {}).get('max_workers')
        if not limit:
            raise DevFlowError('Nested run has no recorded native worker limit')
        _check_capacity(run, limit, replacement)
        if parent.get('workspace') != run.get('workspace') or parent.get('candidate_revision') != run.get('current_revision'):
            raise DevFlowError('Child task must use the parent workspace and candidate revision')
        parent_scopes = parent.get('read_scope') or []
        if not parent_scopes or any(not any(scope_contains(run['workspace'], scope, run['workspace'], child)
                                            for scope in parent_scopes) for child in read_scope):
            raise DevFlowError('Child read_scope must be an explicit subset of its parent read_scope')
        family_root = parent.get('parent_task_id') or parent_task_id
        family = [t for t in run.get('tasks', [])
                  if t.get('parent_task_id') == family_root and t.get('parent_task_id') is not None]
        occupied_slots = {t.get('child_slot') or t['task_id'] for t in family}
        if replacement and replacement in known:
            old = known[replacement]
            if old.get('parent_task_id') != family_root:
                raise DevFlowError('A child replacement must stay in the same delegation family')
        if len(occupied_slots) >= MAX_CHILDREN_PER_PARENT and not replacement:
            raise DevFlowError('Parent delegation has used its two child assignment slots')
        if replacement:
            old = known.get(replacement)
            if not old or old.get('parent_task_id') != family_root or old.get('status') == 'done':
                raise DevFlowError('Replacement must reference an unfinished child in this parent family')
        return {'parent_task_id': parent_task_id, 'depth': parent.get('depth', 1) + 1,
                'delegation': {'enabled': False}, 'family_root': family_root}

    if can_delegate:
        if role not in PARENT_ROLES or write_scope:
            raise DevFlowError('Only read-only architect, reviewer or tester tasks can delegate')
        if not read_scope or any(not isinstance(path, str) or not path.strip() for path in read_scope):
            raise DevFlowError('Delegating parents need an explicit nonempty read_scope')
        for path in read_scope:
            _safe_scope(run['workspace'], path)
        if not isinstance(native_evidence, str) or not native_evidence.strip():
            raise DevFlowError('Delegation requires concrete live native-nesting preflight evidence')
        if type(native_max_workers) is not int or not 2 <= native_max_workers <= MAX_GLOBAL_WORKERS:
            raise DevFlowError('Set --native-max-workers from 2 to 4 after the live native preflight')
        existing_limit = (run.get('nesting') or {}).get('max_workers')
        if existing_limit is not None and existing_limit != native_max_workers:
            raise DevFlowError('The run-wide native worker limit is already fixed')
        _check_capacity(run, native_max_workers, replacement)
        return {'parent_task_id': None, 'depth': 1,
                'delegation': {'enabled': True, 'native_preflight': native_evidence.strip()},
                'native_max_workers': native_max_workers}

    if parent_task_id is None and (native_evidence is not None or native_max_workers is not None):
        raise DevFlowError('Native nesting evidence/limit can only accompany --can-delegate')
    if run.get('nesting'):
        if any(t.get('status') in ('pending', 'active') for t in run.get('tasks', [])):
            raise DevFlowError('Nesting run has active reservations; assign a child or finish current tasks first')
    return None


def apply_assignment(run, task, grant):
    if grant is None:
        return task
    task.update({key: grant[key] for key in ('parent_task_id', 'depth', 'delegation')})
    if grant.get('family_root'):
        task['family_root'] = grant['family_root']
    if grant.get('child_slot'):
        task['child_slot'] = grant['child_slot']
    elif task.get('parent_task_id'):
        task['child_slot'] = task['task_id']
    if grant.get('native_max_workers') is not None:
        run.setdefault('nesting', {'max_workers': grant['native_max_workers'],
                                   'enabled_at': task.get('assigned_at')})
    return task


def result_blockers(run, task, result):
    blockers = []
    trace = result.get('subdelegation_trace')
    if trace is not None:
        children = [t for t in run.get('tasks', []) if t.get('parent_task_id') == task.get('task_id')]
        child_ids = {t['task_id'] for t in children}
        if set(trace['child_task_ids']) != child_ids:
            blockers.append('subdelegation_trace must list exactly the recorded direct children')
        if any(t.get('status') != 'done' for t in children):
            blockers.append('subdelegation_trace cannot report unfinished children')
    if result.get('status') == 'done':
        children = [t for t in run.get('tasks', []) if t.get('parent_task_id') == task.get('task_id')]
        unfinished = [child['task_id'] for child in children if child.get('status') != 'done']
        if unfinished:
            blockers.append('Delegating parent cannot finish before every child is done: ' + ', '.join(unfinished))
        child_workers = {(child.get('result') or {}).get('worker_id') for child in children}
        child_workers.discard(None)
        active_children = [w.get('worker_id') for w in run.get('workers', [])
                           if w.get('status') not in ('done', 'cancelled_confirmed')
                           and (w.get('task_id') in {child['task_id'] for child in children}
                                or w.get('worker_id') in child_workers)]
        if active_children:
            blockers.append('Child native workers must be observed stopped before parent completion: '
                            + ', '.join(active_children))
        if task.get('role') == 'reviewer' and (result.get('review') or {}).get('verdict') == 'passed':
            child_workers = {(child.get('result') or {}).get('worker_id') for child in children}
            child_workers.discard(None)
            if child_workers & set(run.get('authors', [])):
                blockers.append('Reviewer cannot pass when a child is an author on the candidate')
    return blockers


def task_blockers(run, task):
    """Additional final-result guards for parent/child completion."""
    blockers = []
    children = [t for t in run.get('tasks', []) if t.get('parent_task_id') == task.get('task_id')]
    unfinished = [child['task_id'] for child in children if child.get('status') != 'done']
    if unfinished:
        blockers.append('Delegating parent cannot finish before every child is done: ' + ', '.join(unfinished))
    if task.get('parent_task_id'):
        parent = next((t for t in run.get('tasks', []) if t['task_id'] == task['parent_task_id']), None)
        if parent is None:
            blockers.append('Child task has no recorded parent')
        elif (task.get('depth') != 2 or parent.get('depth') != 1
              or not parent.get('delegation', {}).get('enabled')
              or task.get('delegation', {}).get('enabled') or task.get('write_scope')
              or task.get('role') not in LEAF_ROLES):
            blockers.append('Child task has invalid delegation metadata')
    if task.get('role') == 'reviewer' and children:
        review = (task.get('result') or {}).get('review') or {}
        child_workers = {(child.get('result') or {}).get('worker_id') for child in children}
        child_workers.discard(None)
        if review.get('verdict') == 'passed' and child_workers & set(run.get('authors', [])):
            blockers.append('Reviewer used a child who is an author on the candidate')
    return blockers

