"""Optional independent review for lite records, bound to an exact diff and revision."""
import copy
from pathlib import Path
from . import gitops, state
from .storage import DevFlowError, atomic_write, digest, now

VERDICTS = ('passed', 'changes_required', 'incomplete')
MAX_CHANGE_CYCLES = 2
SESSION_MODEL_HINT = ('Lite delegates the work to pol-lite; a light session model (e.g. Sonnet) is enough '
                      'for the Coordinator.')


def diff_path(data, lite_id):
    return Path(data) / 'lite' / (lite_id + '.review.diff')


def _checkout(record):
    live = gitops.inspect(record['repository'])
    if live['branch'] != record['branch']:
        raise DevFlowError('The lite branch is not checked out; switch back to it before reviewing')
    if gitops.tracked_changes(live):
        raise DevFlowError('Lite review needs committed work: commit or preserve tracked/staged changes first')
    return live


def _branch_revision(record):
    try:
        return gitops.git(record['repository'], 'rev-parse', '--verify', 'refs/heads/' + record['branch'])
    except DevFlowError:
        return None


def review_diff(data, record, author_id=None):
    if author_id is not None and not author_id.strip():
        raise DevFlowError('--author-id must be nonempty')
    live = _checkout(record)
    if live['revision'] == record['base_revision']:
        raise DevFlowError('Nothing to review: the lite branch has no commits since its base')
    # Same flags as the full-mode reviewer diff: no external drivers, full binary content.
    diff = gitops.git(record['repository'], 'diff', '--no-ext-diff', '--no-textconv', '--binary', '--full-index',
                      record['base_revision'], live['revision'], '--')
    content = (diff + '\n').encode('utf-8')
    path = diff_path(data, record['id'])
    atomic_write(path, content)
    value = {'path': str(path.resolve()), 'sha256': digest(content), 'base_revision': record['base_revision'],
             'revision': live['revision'], 'author_id': author_id}
    if record.get('review_input') != value and record.get('review'):
        # A review of another diff no longer describes the candidate.
        record.setdefault('review_history', []).append(record['review'] | {'stale': True})
        record['review'] = None
    record['review_input'] = value
    if author_id and author_id not in record.setdefault('authors', []):
        record['authors'].append(author_id)
    return value


def record_review(record, value):
    if not isinstance(value, dict) or set(value) - {'worker_id', 'verdict', 'revision', 'findings'}:
        raise DevFlowError('Lite review accepts only worker_id, verdict, revision and findings')
    if not isinstance(value.get('worker_id'), str) or not value['worker_id'].strip():
        raise DevFlowError('Lite review needs the actual reviewer worker_id')
    if value.get('verdict') not in VERDICTS:
        raise DevFlowError('Lite review verdict must be one of ' + ', '.join(VERDICTS))
    if not isinstance(value.get('revision'), str) or not value['revision'].strip():
        raise DevFlowError('Lite review needs the reviewed revision')
    findings = value.get('findings', [])
    if not isinstance(findings, list):
        raise DevFlowError('findings must be a list')
    for finding in findings:
        state.validate_finding(finding)
    source = record.get('review_input')
    if not source:
        raise DevFlowError('No review input; run _lite review-diff first')
    try:
        unchanged = digest(Path(source['path']).read_bytes()) == source['sha256']
    except OSError:
        unchanged = False
    if not unchanged:
        raise DevFlowError('Lite review diff is missing or modified; run _lite review-diff again')
    live = _checkout(record)
    if not value['revision'] == source['revision'] == live['revision']:
        raise DevFlowError('Review revision is not the current lite candidate; run _lite review-diff again')
    authors = set(record.get('authors', [])) | {source.get('author_id')}
    if value['worker_id'] in authors or value['worker_id'] == record.get('coordinator_id'):
        raise DevFlowError('Lite reviewer must be independent of the author and the Coordinator')
    if record.get('review'):
        record.setdefault('review_history', []).append(record['review'])
    record['review'] = {'verdict': value['verdict'], 'worker_id': value['worker_id'], 'revision': value['revision'],
                        'findings': copy.deepcopy(findings), 'at': now()}
    state.mark_features(record, 'review:lite')
    if value['verdict'] == 'changes_required':
        record['review_cycles'] = record.get('review_cycles', 0) + 1
    escalate = record.get('review_cycles', 0) > MAX_CHANGE_CYCLES
    result = {'review': record['review'], 'review_cycles': record.get('review_cycles', 0), 'escalate': escalate}
    if escalate:
        result['message'] = ('Third changes_required review: stop lite and continue in full mode '
                             '(error|feature --full), preserving the lite branch')
    return result


def status(record):
    if record.get('kind') != 'lite':
        raise DevFlowError('Not a lite record')
    review, source = record.get('review') or {}, record.get('review_input') or {}
    head = _branch_revision(record)
    try:
        unchanged = bool(source) and digest(Path(source['path']).read_bytes()) == source['sha256']
    except OSError:
        unchanged = False
    current = (review.get('verdict') == 'passed' and head is not None and unchanged
               and review.get('revision') == source.get('revision') == head)
    return record | {'branch_revision': head, 'review_current': current}
