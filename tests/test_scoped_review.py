import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCOPED_BLOCKER = ('Scoped re-review: new blocker outside the corrected files; report it as a non-blocking '
                  'follow-up (suggestion/out_of_scope)')
ONE_CORRECTION = ('One correction per candidate: the scoped re-review still requires changes; ask the user before '
                  'another correction (pass --user-approved TEXT)')


def finding(finding_id, location, kind='blocker'):
    return {'id': finding_id, 'kind': kind, 'location': location, 'trigger': 'empty invoice',
            'impact': 'wrong total', 'evidence': 'reproduced'}


class ScopedReviewTests(unittest.TestCase):
    """Validation-scoped re-review after a correction and one correction per candidate (1.0.21)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(*args)
        (self.repo / 'app.py').write_bytes(b'original\n')
        (self.repo / 'lib.py').write_bytes(b'library\n')
        self.git('add', 'app.py', 'lib.py')
        self.git('commit', '-m', 'initial')
        self.count = 0

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True,
                                encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def write(self, value):
        self.count += 1
        path = self.root / f'input-{self.count}.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_bytes(self, run):
        return (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()

    def template(self, run, task, **fields):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.pop('request_ref')
        result.update({'status': 'done', 'summary': 'done', **fields})
        return result

    def change(self, run, role, worker, *extra):
        task = self.run_cli('task', run, '--role', role, '--objective', 'change', '--write-scope', 'app.py', *extra)
        self.count += 1
        (Path(run['workspace']) / 'app.py').write_bytes(f'changed {self.count}\n'.encode())
        self.run_cli('record', run, '--input', self.write(self.template(
            run, task, worker_id=worker, workspace_dirty=True, files_changed=['app.py'])))
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', f'{role} change')
        return task

    def corrected(self):
        """Implementation, review with a corroborated blocker in app.py, refutation and one recorded fixer."""
        run = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Scoped review task', '--criterion', 'c1',
                       '--runtime', 'claude', '--owner', 'co')
        self.change(run, 'implementer', 'impl-1')
        review = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        self.run_cli('record', run, '--input', self.write(self.template(
            run, review, worker_id='rev-1', findings=[finding('F1', 'app.py:1'), finding('F2', 'app.py:1')],
            review={'verdict': 'changes_required', 'coverage': 'Read the full diff'})))
        refute = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'refute', '--refute-from',
                              review['task_id'])
        self.run_cli('record', run, '--input', self.write(self.template(run, refute, worker_id='rev-2', refutation=[
            {'finding_id': 'F1', 'outcome': 'corroborated', 'evidence': 'Total is wrong for empty invoices'},
            {'finding_id': 'F2', 'outcome': 'refuted', 'evidence': 'Guard at app.py:1 handles it'}])))
        self.change(run, 'fixer', 'fix-1', '--correction-key', 'k1')
        return run, review

    def scoped(self, run, review):
        return self.run_cli('task', run, '--role', 'reviewer', '--objective', 'validate fix', '--review-from',
                            review['task_id'])

    def test_scoped_packet_carries_validation_scope_and_frozen_findings(self):
        run, review = self.corrected()
        task = self.scoped(run, review)
        self.assertEqual(task['scope'], 'validation')
        self.assertEqual(task['review_delta']['files'], ['app.py'])
        frozen = {k: v for k, v in finding('F1', 'app.py:1').items() if k != 'kind'}
        # F2 was refuted: only corroborated/inconclusive blockers are frozen for validation.
        self.assertEqual(task['frozen_findings'], [frozen | {'refutation': 'corroborated', 'resolved': False}])
        # A full review has no validation scope.
        plain = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'full review')
        self.assertNotIn('scope', plain)
        self.assertNotIn('frozen_findings', plain)

    def test_new_blocker_outside_the_delta_is_refused(self):
        run, review = self.corrected()
        task = self.scoped(run, review)
        result = self.template(run, task, worker_id='rev-3', findings=[finding('N1', 'lib.py:3')],
                               review={'verdict': 'changes_required', 'coverage': 'Frozen F1 and app.py delta'})
        before = self.state_bytes(run)
        for action in (('record', '--dry-run'), ('record',), ('validate-result',)):
            with self.subTest(action=action):
                self.assertIn(SCOPED_BLOCKER, self.run_cli(action[0], run, *action[1:], '--input',
                                                           self.write(result), ok=False))
        brief = {k: result[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                        'observed_revision', 'result_revision', 'findings', 'review')}
        self.assertIn(SCOPED_BLOCKER, self.run_cli('record', run, '--brief', '--task-id', task['task_id'],
                                                   '--input', self.write(brief), ok=False))
        self.assertEqual(self.state_bytes(run), before)
        # The same observation as a non-blocking follow-up is accepted.
        follow_up = result | {'findings': [finding('N1', 'lib.py:3', 'suggestion'),
                                           finding('N2', 'lib.py', 'out_of_scope')]}
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input', self.write(follow_up))['valid'])

    def test_new_blocker_inside_the_delta_is_accepted(self):
        run, review = self.corrected()
        task = self.scoped(run, review)
        for location in ('app.py:2', 'app.py', './app.py#L2', 'app.py:2-4 (total)'):
            with self.subTest(location=location):
                result = self.template(run, task, worker_id='rev-3', findings=[finding('N1', location)],
                                       review={'verdict': 'changes_required', 'coverage': 'Frozen F1 and delta'})
                self.assertTrue(self.run_cli('record', run, '--dry-run', '--input', self.write(result))['valid'])
        # Full (non-scoped) reviews keep accepting blockers anywhere.
        full = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'full review')
        result = self.template(run, full, worker_id='rev-4', findings=[finding('N3', 'lib.py:3')],
                               review={'verdict': 'changes_required', 'coverage': 'Full diff'})
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input', self.write(result))['valid'])

    def test_one_correction_per_candidate(self):
        run, review = self.corrected()
        task = self.scoped(run, review)
        self.run_cli('record', run, '--input', self.write(self.template(
            run, task, worker_id='rev-3', findings=[finding('N1', 'app.py:2')],
            review={'verdict': 'changes_required', 'coverage': 'Frozen F1 still fails'})))
        before = self.state_bytes(run)
        for extra in ((), ('--blockers-confirmed', 'F1 still breaks totals')):
            with self.subTest(extra=extra):
                self.assertIn(ONE_CORRECTION, self.run_cli(
                    'task', run, '--role', 'fixer', '--objective', 'fix again', '--write-scope', 'app.py',
                    '--correction-key', 'k1', *extra, ok=False))
        self.assertEqual(self.state_bytes(run), before)
        statement = 'User approved a second correction of F1'
        task = self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix again', '--write-scope', 'app.py',
                            '--correction-key', 'k1', '--user-approved', statement,
                            '--blockers-confirmed', 'F1 reproduced again')
        self.assertEqual(task['user_approved'], statement)

    def test_passed_scoped_review_needs_no_user(self):
        run, review = self.corrected()
        task = self.scoped(run, review)
        self.run_cli('record', run, '--input', self.write(self.template(
            run, task, worker_id='rev-3', review={'verdict': 'passed', 'coverage': 'Frozen F1 fixed'})))
        self.run_cli('task', run, '--role', 'fixer', '--objective', 'polish', '--write-scope', 'app.py',
                     '--correction-key', 'k2')


if __name__ == '__main__':
    unittest.main()
