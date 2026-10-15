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
    state.verify_request(record)
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


FINISH_STATES = ('completed', 'partial', 'cancelled')


def finish(record, status='completed', revision=None, reason=None):
    """Close a lite record so stats and cleanup see its real outcome; the branch is never touched."""
    if record.get('status') in state.FINAL_STATES:
        raise DevFlowError(f"Lite record already closed ({record['status']})")
    if status not in FINISH_STATES:
        raise DevFlowError('Lite finish status must be one of ' + ', '.join(FINISH_STATES))
    if status != 'completed' and not (reason or '').strip():
        raise DevFlowError('partial/cancelled needs --reason')
    head = _branch_revision(record)
    if revision:
        # The branch may already be merged and deleted: accept an explicit commit that descends from the base.
        try:
            resolved = gitops.git(record['repository'], 'rev-parse', '--verify', revision + '^{commit}')
            gitops.git(record['repository'], 'merge-base', '--is-ancestor', record['base_revision'], resolved)
        except DevFlowError:
            raise DevFlowError('--revision must be a commit that descends from the lite base revision') from None
        if head and head != resolved:
            raise DevFlowError('--revision differs from the lite branch head; omit it while the branch exists')
        head = resolved
    if status == 'completed':
        if head is None:
            raise DevFlowError('Lite branch not found: pass --revision with the final commit '
                               '(e.g. the merged one) or close as partial/cancelled with --reason')
        if head == record['base_revision']:
            raise DevFlowError('Nothing to complete: no commits since the lite base revision')
        if record.get('review_required') and not status_view(record)['review_current']:
            raise DevFlowError('lite+review needs a current passed review before completing (_lite status)')
    commits = (int(gitops.git(record['repository'], 'rev-list', '--count', f"{record['base_revision']}..{head}"))
               if head else None)
    record.update(status=status, closed_at=now(), final_revision=head, commits=commits,
                  close_reason=(reason or '').strip() or None)
    return {'id': record['id'], 'status': status, 'final_revision': head, 'commits': commits,
            'closed_at': record['closed_at']}


def status_view(record):
    review, source = record.get('review') or {}, record.get('review_input') or {}
    head = _branch_revision(record)
    try:
        unchanged = bool(source) and digest(Path(source['path']).read_bytes()) == source['sha256']
    except OSError:
        unchanged = False
    current = (review.get('verdict') == 'passed' and head is not None and unchanged
               and review.get('revision') == source.get('revision') == head)
    return {'branch_revision': head, 'review_current': current}


def status(record):
    if record.get('kind') != 'lite':
        raise DevFlowError('Not a lite record')
    return record | status_view(record)
