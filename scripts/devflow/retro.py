"""Short process self-assessment per run/lite record, aggregated globally without repository data."""
import datetime as dt
import json
from pathlib import Path
from . import state
from .rules import single_line
from .storage import DevFlowError, FileLock, atomic_write, json_bytes, now, read_json, safe_id

CATEGORIES = ('process', 'rules', 'tooling', 'model', 'environment')
TEXT_LIMIT = 200
LIMITS = {'went_well': 3, 'problems': 5, 'suggestions': 3}
RECENT = 10


def validate(value):
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise DevFlowError('Retro input accepts only went_well, problems and suggestions')
    result = {}
    for field, limit in LIMITS.items():
        items = value.get(field, [])
        if not isinstance(items, list) or len(items) > limit:
            raise DevFlowError(f'{field} must be a list of at most {limit} items')
        result[field] = items
    for field in ('went_well', 'suggestions'):
        for item in result[field]:
            single_line(item, field, TEXT_LIMIT)
    problems = []
    for item in result['problems']:
        if not isinstance(item, dict) or set(item) != {'category', 'text'}:
            raise DevFlowError('Each problem needs exactly category and text')
        if item['category'] not in CATEGORIES:
            raise DevFlowError('Problem category must be one of ' + ', '.join(CATEGORIES))
        problems.append({'category': item['category'], 'text': single_line(item['text'], 'problem', TEXT_LIMIT)})
    result['problems'] = problems
    if not any(result.values()):
        raise DevFlowError('Retro needs at least one went_well, problem or suggestion')
    return result


def journal_path(data):
    return Path(data) / 'retro.jsonl'


def _attach(record, value):
    if record.get('retro'):
        record.setdefault('retro_history', []).append(record['retro'])
    record['retro'] = value | {'at': now()}
    return record['retro']


def _append(data, entry):
    path = journal_path(data)
    with FileLock(path.with_suffix('.lock'), 'retro'):
        previous = path.read_bytes() if path.is_file() else b''
        if previous and not previous.endswith(b'\n'):
            previous += b'\n'
        atomic_write(path, previous + (json.dumps(entry, ensure_ascii=False) + '\n').encode('utf-8'))


def add(data, value, run_id=None, lite_id=None, owner=None):
    if bool(run_id) == bool(lite_id):
        raise DevFlowError('Use exactly one of --run or --lite')
    retro = validate(value)
    data = Path(data)
    if run_id:
        if not owner:
            raise DevFlowError('_retro add --run needs --owner')
        if not (state.run_dir(data, run_id) / 'state.json').is_file():
            raise DevFlowError(f'Unknown run: {run_id}')
        with state.RunLock(data, run_id, owner):
            run = state.load(data, run_id)
            state.require_owner(run, owner)
            stored = _attach(run, retro)
            state.save(data, run, 'retro recorded')
        mode, level, replaced = run.get('mode'), 'full', len(run.get('retro_history', []))
    else:
        path = data / 'lite' / (safe_id(lite_id) + '.json')
        if not path.is_file():
            raise DevFlowError(f'Unknown lite record: {lite_id}')
        with FileLock(path.with_suffix('.lock'), owner or 'retro'):
            record = read_json(path)
            if record.get('kind') != 'lite' or (record.get('coordinator_id') and record['coordinator_id'] != owner):
                raise DevFlowError('Lite ownership mismatch; pass the Coordinator --owner used at start')
            stored = _attach(record, retro)
            atomic_write(path, json_bytes(record))
        mode, replaced = record.get('mode'), len(record.get('retro_history', []))
        level = 'lite+review' if record.get('review_required') else 'lite'
    # Global journal: no repository path, branch or run id, so it can be compared across projects.
    _append(data, {'at': stored['at'], 'mode': mode, 'level': level, 'problems': stored['problems'],
                   'suggestions': stored['suggestions'], 'went_well': stored['went_well']})
    return {'retro': stored, 'replaced_previous': bool(replaced), 'history_size': replaced,
            'journal': str(journal_path(data))}


def _parse_time(value):
    try:
        moment = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def summary(data, since_days=None, category=None):
    """Read-only aggregate of the global journal; never creates the data directory."""
    if since_days is not None and (type(since_days) is not int or since_days <= 0):
        raise DevFlowError('--since needs a positive number of days')
    if category is not None and category not in CATEGORIES:
        raise DevFlowError('--category must be one of ' + ', '.join(CATEGORIES))
    limit = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)) if since_days else None
    path = journal_path(data)
    entries, skipped = [], 0
    if path.is_file():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            moment = _parse_time(entry.get('at')) if isinstance(entry, dict) else None
            if moment is None:
                skipped += 1
                continue
            if limit and moment < limit:
                continue
            entries.append((moment, entry))
    entries.sort(key=lambda item: item[0], reverse=True)
    counts = {name: 0 for name in CATEGORIES}
    problems, suggestions, total = [], [], 0
    for _, entry in entries:
        items = [p for p in entry.get('problems') or [] if isinstance(p, dict) and p.get('category') in CATEGORIES]
        if category:
            items = [p for p in items if p['category'] == category]
            if not items:
                continue
        total += 1
        for item in items:
            counts[item['category']] += 1
            problems.append({'category': item['category'], 'text': item.get('text'), 'at': entry['at'],
                             'level': entry.get('level')})
        suggestions.extend({'text': s, 'at': entry['at'], 'level': entry.get('level')}
                           for s in entry.get('suggestions') or [] if isinstance(s, str))
    result = {'total_retros': total, 'since_days': since_days, 'category': category,
              'problems_by_category': {k: v for k, v in counts.items() if not category or k == category},
              'recent_problems': problems[:RECENT], 'recent_suggestions': suggestions[:RECENT],
              'source': str(path) if path.is_file() else None,
              'note': 'Global across projects; contains no repository paths or run ids'}
    if skipped:
        result['skipped_lines'] = skipped
    return result


# CLI integration -------------------------------------------------------------------------------------------------


def add_parsers(commands):
    p = commands.add_parser('_retro')
    p.add_argument('action', choices=('add',))
    p.add_argument('--run')
    p.add_argument('--lite')
    p.add_argument('--owner')
    p.add_argument('--input', required=True)
    p = commands.add_parser('retro')
    p.add_argument('--since', type=int)
    p.add_argument('--category', choices=CATEGORIES)


def dispatch(args, ctx):
    if args.command == 'retro':
        return summary(ctx.data_dir, args.since, args.category)
    if args.command != '_retro':
        return None
    return add(ctx.data_dir, read_json(args.input), args.run, args.lite, args.owner)
