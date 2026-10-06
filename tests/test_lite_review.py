import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LiteReviewTests(unittest.TestCase):
    """Lite + review level, code map handoff between workers and the lite session model hint."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.data = self.root / 'data'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def start(self, *extra):
        return self.cli('_lite', 'start', '--mode', 'error', '--request', 'Login returns 500', '--owner', 'co', *extra)

    def commit(self, record, text):
        (self.repo / 'app.py').write_text(text)
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix login')
        return self.git('rev-parse', 'HEAD')

    def lite(self, action, record, *args, ok=True):
        return self.cli('_lite', action, '--lite', record['id'], '--owner', 'co', *args, ok=ok)

    def review(self, record, verdict='passed', worker='rev-1', revision=None, ok=True, **extra):
        value = {'worker_id': worker, 'verdict': verdict,
                 'revision': revision or self.git('rev-parse', 'HEAD')} | extra
        return self.lite('review', record, '--input', self.write('review.json', value), ok=ok)

    def saved(self, record):
        return json.loads((self.data / 'lite' / (record['id'] + '.json')).read_text(encoding='utf-8'))

    # Level flags --------------------------------------------------------------------------

    def test_review_level_flags(self):
        result = self.cli('feature', '--lite', '--review', '--plan-only', 'Add phone')
        self.assertEqual(result['level'], 'lite+review')
        self.assertTrue(result['review_requested'])
        self.assertTrue(result['workflow'].endswith('lite.md'))
        auto = self.cli('error', '--review', 'Bug')
        self.assertEqual((auto['level'], auto['review_requested']), ('auto', True))
        full = self.cli('feature', '--full', '--review', 'Phone')
        self.assertEqual((full['level'], full['review_requested']), ('full', True))
        self.assertTrue(full['workflow'].endswith('feature.md'))
        self.assertFalse(self.cli('error', '--lite', 'Bug')['review_requested'])
        self.assertIn('--review', self.cli('optimize', '--review', 'Faster', ok=False))
        self.assertFalse(self.data.exists())

    def test_lite_start_records_review_flag_and_model_hint(self):
        plain = self.start()
        self.assertFalse(plain['review_required'])
        self.assertIn('Sonnet', plain['session_model_hint'])
        self.git('switch', 'main')
        reviewed = self.start('--review')
        self.assertTrue(reviewed['review_required'])
        self.assertTrue(self.saved(reviewed)['review_required'])
        self.assertIn('review-diff', reviewed['next_action'])
        self.cli('_lite', 'status', '--lite', reviewed['id'], '--review', ok=False)

    # Review diff --------------------------------------------------------------------------

    def test_review_diff_writes_bound_artifact_and_refuses_tracked_changes(self):
        record = self.start('--review')
        self.assertIn('no commits', self.lite('review-diff', record, ok=False))
        head = self.commit(record, 'fixed\n')
        (self.repo / 'notes.txt').write_text('untracked preserved file\n')
        source = self.lite('review-diff', record, '--author-id', 'lite-1')
        content = Path(source['path']).read_bytes()
        self.assertEqual(Path(source['path']), (self.data / 'lite' / (record['id'] + '.review.diff')).resolve())
        self.assertEqual(source['sha256'], hashlib.sha256(content).hexdigest())
        self.assertIn(b'+fixed', content)
        self.assertNotIn(b'notes.txt', content)
        self.assertEqual((source['base_revision'], source['revision'], source['author_id']),
                         (record['base_revision'], head, 'lite-1'))
        self.assertEqual(self.saved(record)['review_input'], source)
        self.assertIn('ownership', self.cli('_lite', 'review-diff', '--lite', record['id'], '--owner', 'other',
                                            ok=False))
        (self.repo / 'app.py').write_text('uncommitted\n')
        self.assertIn('tracked', self.lite('review-diff', record, ok=False))
        self.git('checkout', '--', 'app.py')
        self.git('switch', 'main')
        self.assertIn('not checked out', self.lite('review-diff', record, ok=False))

    # Review -------------------------------------------------------------------------------

    def test_independent_review_is_accepted_and_current(self):
        record = self.start('--review')
        self.commit(record, 'fixed\n')
        self.lite('review-diff', record, '--author-id', 'lite-1')
        self.assertFalse(self.cli('_lite', 'status', '--lite', record['id'])['review_current'])
        finding = {'kind': 'suggestion', 'summary': 'name could be clearer'}
        result = self.review(record, findings=[finding])
        self.assertFalse(result['escalate'])
        self.assertEqual(result['review']['worker_id'], 'rev-1')
        self.assertEqual(result['review']['findings'], [finding])
        status = self.cli('_lite', 'status', '--lite', record['id'])
        self.assertTrue(status['review_current'])
        self.assertEqual(status['review']['verdict'], 'passed')
        # Status stays meaningful after switching away: it reads the lite branch, not the checkout.
        self.git('switch', 'main')
        self.assertTrue(self.cli('_lite', 'status', '--lite', record['id'])['review_current'])

    def test_review_rejects_author_coordinator_and_bad_input(self):
        record = self.start('--review')
        self.commit(record, 'fixed\n')
        self.assertIn('review-diff', self.review(record, ok=False))
        self.lite('review-diff', record, '--author-id', 'lite-1')
        for worker in ('lite-1', 'co'):
            self.assertIn('independent', self.review(record, worker=worker, ok=False))
        self.review(record, verdict='ok', ok=False)
        self.review(record, worker='', ok=False)
        self.review(record, findings=[{'kind': 'blocker', 'location': 'app.py'}], ok=False)
        self.review(record, extra_field=1, ok=False)
        self.assertIsNone(self.saved(record).get('review'))
        blocker = {'kind': 'blocker', 'location': 'app.py:1', 'trigger': 'login', 'impact': '500',
                   'evidence': 'trace'}
        self.assertEqual(self.review(record, verdict='changes_required', findings=[blocker])['review_cycles'], 1)

    def test_review_rejects_moved_head_or_modified_diff(self):
        record = self.start('--review')
        reviewed = self.commit(record, 'fixed\n')
        source = self.lite('review-diff', record, '--author-id', 'lite-1')
        Path(source['path']).write_bytes(Path(source['path']).read_bytes() + b'tampered\n')
        self.assertIn('modified', self.review(record, ok=False))
        self.lite('review-diff', record, '--author-id', 'lite-1')
        self.commit(record, 'fixed again\n')
        self.assertIn('current lite candidate', self.review(record, revision=reviewed, ok=False))
        self.assertIn('current lite candidate', self.review(record, ok=False))
        self.assertIsNone(self.saved(record).get('review'))

    def test_new_commits_make_previous_review_stale(self):
        record = self.start('--review')
        self.commit(record, 'fixed\n')
        self.lite('review-diff', record, '--author-id', 'lite-1')
        self.review(record)
        self.commit(record, 'fixed again\n')
        status = self.cli('_lite', 'status', '--lite', record['id'])
        self.assertFalse(status['review_current'])
        source = self.lite('review-diff', record, '--author-id', 'lite-1')
        saved = self.saved(record)
        self.assertIsNone(saved['review'])
        self.assertTrue(saved['review_history'][-1]['stale'])
        self.assertEqual(saved['review_input'], source)
        self.assertFalse(self.cli('_lite', 'status', '--lite', record['id'])['review_current'])
        self.review(record, worker='rev-2')
        self.assertTrue(self.cli('_lite', 'status', '--lite', record['id'])['review_current'])

    def test_third_changes_required_escalates_to_full(self):
        record = self.start('--review')
        for cycle, text in enumerate(('one\n', 'two\n', 'three\n'), 1):
            self.commit(record, text)
            self.lite('review-diff', record, '--author-id', 'lite-1')
            result = self.review(record, verdict='changes_required')
            self.assertEqual(result['review_cycles'], cycle)
            self.assertEqual(result['escalate'], cycle == 3)
        self.assertIn('full', result['message'])
        saved = self.saved(record)
        self.assertEqual(saved['review']['verdict'], 'changes_required')
        self.assertEqual(len(saved['review_history']), 2)
        self.assertFalse(self.cli('_lite', 'status', '--lite', record['id'])['review_current'])

    def test_purge_history_removes_review_diff(self):
        record = self.start('--review')
        self.commit(record, 'fixed\n')
        source = self.lite('review-diff', record, '--author-id', 'lite-1')
        self.git('switch', 'main')
        self.git('merge', '--no-ff', '-m', 'merge', record['branch'])
        self.cli('cleanup', '--apply')
        self.assertTrue(Path(source['path']).exists())
        self.cli('cleanup', '--apply', '--purge-history')
        self.assertFalse(Path(source['path']).exists())
        self.assertFalse((self.data / 'lite' / (record['id'] + '.json')).exists())

    # Code map handoff ---------------------------------------------------------------------

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def explorer_result(self, run, **extra):
        task = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map login')
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        return task, result | {'worker_id': 'exp-1', 'summary': 'Login handler lives in app.py'} | extra

    def test_code_map_is_validated(self):
        run = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Phone', '--criterion', 'c1',
                       '--runtime', 'claude', '--owner', 'co')
        _, result = self.explorer_result(run)
        many = [{'path': 'app.py'}] * 51
        for bad in ([{'path': '../outside.py'}], [{'path': 'app.py', 'lines': 'ten'}], many,
                    [{'path': 'app.py', 'extra': 'x'}], [{'path': 'app.py', 'symbol': 3}], {'path': 'app.py'}):
            self.run_cli('record', run, '--dry-run', '--input', self.write('bad.json', result | {'code_map': bad}),
                         ok=False)
        code_map = [{'path': 'app.py', 'symbol': 'login', 'lines': '1-40', 'why': 'raises 500'},
                    {'path': 'app.py', 'lines': '12'}] + [{'path': 'app.py'}] * 48
        self.run_cli('record', run, '--input', self.write('r.json', result | {'code_map': code_map}))
        self.assertEqual(self.run_cli('show', run)['run']['tasks'][0]['result']['code_map'], code_map)

    def test_context_from_hands_over_summary_and_code_map(self):
        run = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Phone', '--criterion', 'c1',
                       '--runtime', 'claude', '--owner', 'co')
        mapped, result = self.explorer_result(run, code_map=[{'path': 'app.py', 'symbol': 'login'}])
        self.assertIn('recorded result', self.run_cli('task', run, '--role', 'explorer', '--objective', 'more',
                                                      '--context-from', mapped['task_id'], ok=False))
        self.run_cli('record', run, '--input', self.write('r.json', result))
        plain, result = self.explorer_result(run)
        self.run_cli('record', run, '--input', self.write('r2.json', result))
        self.run_cli('task', run, '--role', 'implementer', '--objective', 'fix', '--context-from', 'task-missing',
                     ok=False)
        self.run_cli('refresh', run, '--context-from', mapped['task_id'], ok=False)
        extra = {'relevant_context': ['user prefers small diffs']}
        task = self.run_cli('task', run, '--role', 'implementer', '--objective', 'fix', '--write-scope', 'app.py',
                            '--input', self.write('ctx.json', extra), '--context-from', mapped['task_id'],
                            '--context-from', plain['task_id'])
        self.assertEqual(task['relevant_context'], [
            'user prefers small diffs',
            {'from_task': mapped['task_id'], 'role': 'explorer', 'summary': 'Login handler lives in app.py',
             'code_map': [{'path': 'app.py', 'symbol': 'login'}]},
            {'from_task': plain['task_id'], 'role': 'explorer', 'summary': 'Login handler lives in app.py',
             'code_map': []}])


if __name__ == '__main__':
    unittest.main()
