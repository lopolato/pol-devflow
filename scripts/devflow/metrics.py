"""Per-worker usage records (model, tokens, time) and read-only aggregation for tuning."""
import datetime as dt
import json
from pathlib import Path
from . import config, gitops, state
from .storage import DevFlowError, FileLock, atomic_write, json_bytes, now, read_json

SOURCES = ('runtime', 'estimate', 'unavailable')
ROLES = (*config.ROLES,)
AUTO_FEATURES = ('level:lite', 'level:lite+review', 'level:full', 'executor:orca', 'review:lite', 'nesting',
                 'checkpoint', 'template', 'dry_run', 'check_close', 'context_from', 'budget_minutes', 'incident',
                 'identity_warning')
DECLARED_FEATURES = ('codegraph', 'context7', 'memory', 'profile_reused', 'profile_saved', 'retro', 'rules')
COMMANDS = ('cleanup',)  # Only state-changing run-less invocations (cleanup --apply) are logged.


def declare(record, name):
    """Coordinator-declared feature the CLI cannot observe itself."""
    if name not in DECLARED_FEATURES:
        raise DevFlowError('Unknown feature; declare one of ' + ', '.join(DECLARED_FEATURES))
    state.mark_features(record, name)
    return {'features': record['features']}


def note_readonly(data, run_id, name):
    """Feature use of a read-only helper: kept beside state.json so the run state bytes stay unchanged."""
    path = state.run_dir(data, run_id) / 'features.json'
    with FileLock(path.with_suffix('.lock'), 'features'):
        current = read_json(path) if path.exists() else []
        if name not in current:
            atomic_write(path, json_bytes(sorted({*current, name})))


def log_command(data, command, flags):
    """Global usage line for a state-changing run-less command: flag names only, never paths, branches or repositories."""
    folder = Path(data) / 'usage'
    if not Path(data).is_dir():
        return  # Never create the data home just to count a command.
    line = json.dumps({'command': command, 'flags': sorted(flags), 'at': now()}) + '\n'
    try:
        folder.mkdir(exist_ok=True)
        with (folder / 'commands.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(line)
    except OSError:
        pass  # Usage counting never breaks the command.


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


def _limit(since_days):
    if since_days is not None and (type(since_days) is not int or since_days <= 0):
        raise DevFlowError('--since needs a positive number of days')
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)) if since_days else None


def _selected(data, repository, all_repos, limit):
    ours = None if all_repos else _identity(repository)
    if not all_repos and ours is None:
        raise DevFlowError('stats needs a Git repository; use --all for every project')
    for level, record in _records(data):
        if ours and record.get('git_common_dir') != ours and _identity(record.get('repository', '')) != ours:
            continue
        created = record.get('created_at')
        if limit and created and dt.datetime.fromisoformat(created) < limit:
            continue
        yield level, record


def _commands(data, limit):
    path = Path(data) / 'usage' / 'commands.jsonl'
    counts = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
    except OSError:
        lines = []
    for line in lines:
        try:
            item = json.loads(line)
            if limit and dt.datetime.fromisoformat(item['at']) < limit:
                continue
            bucket = counts.setdefault(item['command'], {'count': 0, 'flags': {}})
        except (ValueError, KeyError, TypeError, AttributeError):
            continue  # A damaged line never breaks stats.
        bucket['count'] += 1
        for flag in item.get('flags') or []:
            bucket['flags'][flag] = bucket['flags'].get(flag, 0) + 1
    return counts


def features(data, repository=None, all_repos=False, since_days=None):
    """Which DevFlow features were used in the window (runs, lite records and global commands)."""
    limit = _limit(since_days)
    counts = {name: {'runs': 0, 'lite': 0} for name in (*AUTO_FEATURES, *DECLARED_FEATURES)}
    records = 0
    for level, record in _selected(data, repository, all_repos, limit):
        records += 1
        for name in record.get('features') or []:
            counts.setdefault(name, {'runs': 0, 'lite': 0})['runs' if level == 'full' else 'lite'] += 1
    commands = _commands(data, limit) if all_repos else None
    never = [n for n in (*AUTO_FEATURES, *DECLARED_FEATURES) if not counts[n]['runs'] + counts[n]['lite']]
    if commands is not None:
        never += ['command:' + c for c in COMMANDS if c not in commands]
    return {'scope': 'all repositories' if all_repos else 'current repository', 'since_days': since_days,
            'records': records, 'features': counts, 'commands': commands, 'never_used': never,
            'note': 'Counts runs/lite records that used each feature. commands.jsonl is global (not per '
                    'repository): ' + ('included' if all_repos else 'only included with --all') + '.'}


def stats(data, repository=None, all_repos=False, since_days=None):
    limit = _limit(since_days)
    tasks, roles, unmeasured = {}, {}, 0
    for level, record in _selected(data, repository, all_repos, limit):
        key = f"{level}:{record.get('mode')}"
        bucket = tasks.setdefault(key, {'count': 0, 'tokens': 0, 'measured': 0, 'status': {}})
        bucket['count'] += 1
        timing = state.elapsed_timing(record)
        bucket.setdefault('wall_clock_elapsed_seconds', 0)
        bucket.setdefault('wall_clock_known', 0)
        if timing['elapsed_seconds'] is not None:
            bucket['wall_clock_elapsed_seconds'] += timing['elapsed_seconds']
            bucket['wall_clock_known'] += 1
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
        bucket['avg_wall_clock_elapsed_seconds'] = (round(bucket['wall_clock_elapsed_seconds'] /
            bucket['wall_clock_known'], 3) if bucket['wall_clock_known'] else None)
    total = sum(r['tokens'] for r in roles.values())
    for role in roles.values():
        role['share'] = round(role['tokens'] / total, 3) if total else None
    return {'scope': 'all repositories' if all_repos else 'current repository', 'since_days': since_days,
            'tasks': tasks, 'roles': dict(sorted(roles.items(), key=lambda kv: -kv[1]['tokens'])),
            'total_tokens_known': total, 'tasks_without_metrics': unmeasured,
            'note': 'Only recorded usage is counted; unavailable values are never estimated. Wall-clock '
                    'elapsed includes waiting, coordination and checks, not agent compute; overlapping runs are not additive.'}
