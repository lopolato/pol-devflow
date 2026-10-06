"""Per-worker usage records (model, tokens, time) and read-only aggregation for tuning."""
import datetime as dt
from pathlib import Path
from . import config, gitops, state
from .storage import DevFlowError, now, read_json

SOURCES = ('runtime', 'estimate', 'unavailable')
ROLES = (*config.ROLES,)


def entry(value):
    """Validate one usage record; unknown numbers stay None instead of being invented."""
    if not isinstance(value, dict) or set(value) - {'role', 'model', 'tokens', 'duration_ms', 'tool_uses',
                                                    'source', 'task_id', 'worker_id', 'phase'}:
        raise DevFlowError('Usage accepts role, model, tokens, duration_ms, tool_uses, source, task_id, worker_id, phase')
    if value.get('role') not in ROLES:
        raise DevFlowError('Usage needs a DevFlow role')
    for name in ('tokens', 'duration_ms', 'tool_uses'):
        number = value.get(name)
        if number is not None and (type(number) is not int or number < 0):
            raise DevFlowError(f'Usage {name} must be a nonnegative integer or null')
    for name in ('model', 'task_id', 'worker_id', 'phase'):
        text = value.get(name)
        if text is not None and (not isinstance(text, str) or not text.strip() or any(ord(c) < 32 for c in text)):
            raise DevFlowError(f'Usage {name} must be a single-line string or null')
    source = value.get('source') or ('runtime' if value.get('tokens') is not None else 'unavailable')
    if source not in SOURCES:
        raise DevFlowError('Usage source must be runtime, estimate or unavailable')
    return {'role': value['role'], 'model': value.get('model'), 'tokens': value.get('tokens'),
            'duration_ms': value.get('duration_ms'), 'tool_uses': value.get('tool_uses'), 'source': source,
            'task_id': value.get('task_id'), 'worker_id': value.get('worker_id'), 'phase': value.get('phase'),
            'at': now()}


def add(record, value):
    item = entry(value)
    record.setdefault('metrics', []).append(item)
    return item


def _records(data):
    data = Path(data)
    for path in sorted((data / 'runs').glob('*/state.json')) if (data / 'runs').is_dir() else []:
        try:
            run = state.load(data, path.parent.name)
        except DevFlowError:
            continue
        yield 'full', run
    for path in sorted((data / 'lite').glob('*.json')) if (data / 'lite').is_dir() else []:
        try:
            record = read_json(path)
        except DevFlowError:
            continue
        if record.get('kind') == 'lite':
            yield 'lite', record


def _identity(repository):
    try:
        return gitops.common_dir(repository)
    except DevFlowError:
        return None


def stats(data, repository=None, all_repos=False, since_days=None):
    if since_days is not None and (type(since_days) is not int or since_days <= 0):
        raise DevFlowError('--since needs a positive number of days')
    limit = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)) if since_days else None
    ours = None if all_repos else _identity(repository)
    if not all_repos and ours is None:
        raise DevFlowError('stats needs a Git repository; use --all for every project')
    tasks, roles, unmeasured = {}, {}, 0
    for level, record in _records(data):
        if ours and record.get('git_common_dir') != ours and _identity(record.get('repository', '')) != ours:
            continue
        created = record.get('created_at')
        if limit and created and dt.datetime.fromisoformat(created) < limit:
            continue
        key = f"{level}:{record.get('mode')}"
        bucket = tasks.setdefault(key, {'count': 0, 'tokens': 0, 'measured': 0, 'status': {}})
        bucket['count'] += 1
        status = record.get('status', 'unknown')
        bucket['status'][status] = bucket['status'].get(status, 0) + 1
        items = record.get('metrics', [])
        if not items:
            unmeasured += 1
        if any(i.get('tokens') is not None for i in items):
            bucket['measured'] += 1
        for item in items:
            role = roles.setdefault(item['role'], {'calls': 0, 'tokens': 0, 'tokens_known': 0,
                                                   'duration_ms': 0, 'duration_known': 0, 'models': {}})
            role['calls'] += 1
            if item.get('tokens') is not None:
                role['tokens'] += item['tokens']
                role['tokens_known'] += 1
                bucket['tokens'] += item['tokens']
            if item.get('duration_ms') is not None:
                role['duration_ms'] += item['duration_ms']
                role['duration_known'] += 1
            model = item.get('model') or 'unknown'
            role['models'][model] = role['models'].get(model, 0) + 1
    for role in roles.values():
        role['avg_tokens'] = role['tokens'] // role['tokens_known'] if role['tokens_known'] else None
        role['avg_duration_s'] = round(role['duration_ms'] / role['duration_known'] / 1000, 1) if role['duration_known'] else None
    for bucket in tasks.values():
        bucket['avg_tokens_measured'] = bucket['tokens'] // bucket['measured'] if bucket['measured'] else None
    total = sum(r['tokens'] for r in roles.values())
    for role in roles.values():
        role['share'] = round(role['tokens'] / total, 3) if total else None
    return {'scope': 'all repositories' if all_repos else 'current repository', 'since_days': since_days,
            'tasks': tasks, 'roles': dict(sorted(roles.items(), key=lambda kv: -kv[1]['tokens'])),
            'total_tokens_known': total, 'tasks_without_metrics': unmeasured,
            'note': 'Only recorded usage is counted; unavailable values are never estimated.'}
