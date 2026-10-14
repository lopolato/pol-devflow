import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLAN = {'lenses': ['security', 'money'], 'reason': 'Touches invoice permissions'}
SELF_REVIEW_MISSING = 'self_review missing for planned lenses'


class FirstPassTests(unittest.TestCase):
    """Review plan with lenses, worker self-review and the second-round fixer gate (1.0.20)."""

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
        self.git('add', 'app.py')
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

    def start(self):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'First pass task', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co')

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_bytes(self, run):
        return (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()

    def show(self, run):
        return self.run_cli('show', run)['run']

    def plan(self, run, value=PLAN, ok=True):
        return self.run_cli('update', run, '--input', self.write({'review_plan': value}), ok=ok)

    def template(self, run, task, **fields):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.pop('request_ref')
        result.update({'status': 'done', 'summary': 'done', **fields})
        return result

    def review(self, run, verdict, coverage, worker='rev-1'):
        task = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        result = self.template(run, task, worker_id=worker, review={'verdict': verdict, 'coverage': coverage})
        return task, result

    def implement(self, run, role='implementer', *extra):
        task = self.run_cli('task', run, '--role', role, '--objective', 'change', '--write-scope', 'app.py', *extra)
        self.count += 1
        (Path(run['workspace']) / 'app.py').write_bytes(f'changed {self.count}\n'.encode())
        return task, self.template(run, task, worker_id='impl-1', workspace_dirty=True, files_changed=['app.py'])

    def cancel(self, run, task):
        extra = {'review': {'verdict': 'incomplete', 'coverage': 'stopped before security and money'}}
        result = self.template(run, task, worker_id='w-cancel', status='cancelled',
                               **(extra if task['role'] == 'reviewer' else {}))
        self.run_cli('record', run, '--input', self.write(result))

    # 1a. Review plan ------------------------------------------------------------------------------------

    def test_review_plan_validation_replacement_and_history(self):
        run = self.start()
        before = self.state_bytes(run)
        for bad in ({'lenses': ['security']}, {'lenses': [], 'reason': 'r'}, {'lenses': ['speed'], 'reason': 'r'},
                    {'lenses': ['money', 'money'], 'reason': 'r'}, {'lenses': 'money', 'reason': 'r'},
                    {'lenses': ['money'], 'reason': ' '}, {'lenses': ['money'], 'reason': 'two\nlines'},
                    {'lenses': ['money'], 'reason': 'x' * 201}, {'lenses': ['money'], 'reason': 'r', 'extra': 1},
                    ['money']):
            with self.subTest(bad=bad):
                self.plan(run, bad, ok=False)
        self.assertEqual(self.state_bytes(run), before)
        self.assertNotIn('review_plan', self.show(run)['features'])
        first = self.plan(run)
        self.assertEqual({k: first['review_plan'][k] for k in ('lenses', 'reason')}, PLAN)
        self.assertIn('at', first['review_plan'])
        self.assertNotIn('review_plan_history', first)
        self.assertIn('review_plan', first['features'])
        every = {'lenses': ['requirements', 'security', 'money', 'communications', 'data', 'concurrency', 'tests'],
                 'reason': 'x' * 200}
        second = self.plan(run, every)
        self.assertEqual(second['review_plan']['lenses'], every['lenses'])
        self.assertEqual(second['review_plan_history'], [first['review_plan']])

    def test_packets_include_review_plan_for_planned_roles(self):
        run = self.start()
        before = self.run_cli('task', run, '--role', 'implementer', '--objective', 'early', '--write-scope', 'app.py')
        self.assertIn('review_plan', before)
        self.assertIsNone(before['review_plan'])
        self.cancel(run, before)
        plan = self.plan(run)['review_plan']
        for role, extra in (('implementer', ('--write-scope', 'app.py')),
                            ('fixer', ('--write-scope', 'app.py', '--correction-key', 'k1')),
                            ('tester', ()), ('reviewer', ())):
            with self.subTest(role=role):
                task = self.run_cli('task', run, '--role', role, '--objective', 'work', *extra)
                self.assertEqual(task['review_plan'], plan)
                self.cancel(run, task)
        explorer = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        self.assertNotIn('review_plan', explorer)

    def test_reviewer_coverage_must_name_every_planned_lens(self):
        run = self.start()
        self.plan(run)
        task, result = self.review(run, 'passed', 'Checked security of the diff')
        expected = 'Review coverage must address every planned lens: missing money'
        before = self.state_bytes(run)
        for extra in (('--dry-run',), ()):
            with self.subTest(extra=extra):
                self.assertIn(expected, self.run_cli('record', run, '--input', self.write(result), *extra, ok=False))
        self.assertIn(expected, self.run_cli('validate-result', run, '--input', self.write(result), ok=False))
        brief = {k: result[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                        'observed_revision', 'result_revision', 'review')}
        self.assertIn(expected, self.run_cli('record', run, '--brief', '--task-id', task['task_id'],
                                             '--input', self.write(brief), ok=False))
        none = result | {'review': {'verdict': 'changes_required', 'coverage': 'Read the diff'}}
        self.assertIn('missing security, money', self.run_cli('record', run, '--input', self.write(none), ok=False))
        self.assertEqual(self.state_bytes(run), before)
        # Case-insensitive substring match; the brief path and dry-run accept the same coverage.
        covered = {'verdict': 'passed', 'coverage': 'SECURITY: roles checked; Money: VAT totals checked'}
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input',
                                     self.write(result | {'review': covered}))['valid'])
        recorded = self.run_cli('record', run, '--brief', '--task-id', task['task_id'],
                                '--input', self.write(brief | {'review': covered}))
        self.assertEqual(recorded['review']['verdict'], 'passed')

    def test_reviewer_without_plan_keeps_free_coverage(self):
        run = self.start()
        _, result = self.review(run, 'passed', 'Inspected complete diff')
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input', self.write(result))['valid'])

    def test_self_review_validation_and_warning(self):
        run = self.start()
        self.plan(run)
        task, result = self.implement(run)
        dry = self.run_cli('record', run, '--dry-run', '--input', self.write(result))
        self.assertIn(SELF_REVIEW_MISSING, dry['warnings'])
        for bad in ('ok', [{'lens': 'speed', 'status': 'ok'}], [{'lens': 'money', 'status': 'fine'}],
                    [{'lens': 'money'}], [{'lens': 'money', 'status': 'ok', 'note': 'a\nb'}],
                    [{'lens': 'money', 'status': 'ok', 'note': 'x' * 201}],
                    [{'lens': 'money', 'status': 'ok'}, {'lens': 'money', 'status': 'risk'}],
                    [{'lens': 'money', 'status': 'ok', 'extra': 1}], ['money']):
            with self.subTest(bad=bad):
                self.run_cli('record', run, '--dry-run', '--input', self.write(result | {'self_review': bad}),
                             ok=False)
        good = [{'lens': 'security', 'status': 'ok', 'note': 'Only admins reach the view'},
                {'lens': 'money', 'status': 'risk', 'note': 'Rounding of VAT not covered by tests'},
                {'lens': 'tests', 'status': 'not_applicable'}]
        checked = self.run_cli('record', run, '--dry-run', '--input', self.write(result | {'self_review': good}))
        self.assertNotIn(SELF_REVIEW_MISSING, checked['warnings'])
        recorded = self.run_cli('record', run, '--input', self.write(result | {'self_review': good}))
        self.assertNotIn(SELF_REVIEW_MISSING, recorded['warnings'])
        self.assertIn('self_review', recorded['features'])
        self.assertEqual(recorded['tasks'][0]['result']['self_review'], good)
        # Only implementer/fixer results may carry a self_review.
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Change')
        tester = self.run_cli('task', run, '--role', 'tester', '--objective', 'test')
        tested = self.template(run, tester, worker_id='test-1', self_review=good[:1])
        self.assertIn('self_review', self.run_cli('record', run, '--dry-run', '--input', self.write(tested), ok=False))

    def test_missing_self_review_warns_without_blocking(self):
        run = self.start()
        self.plan(run)
        task, result = self.implement(run)
        recorded = self.run_cli('record', run, '--input', self.write(result))
        self.assertIn(SELF_REVIEW_MISSING, recorded['warnings'])
        self.assertEqual(recorded['tasks'][0]['status'], 'done')
        self.assertNotIn('warnings', self.show(run))
        # Brief results accept self_review too.
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Change')
        fixer, full = self.implement(run, 'fixer', '--correction-key', 'k1')
        brief = {k: full[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                      'observed_revision', 'result_revision')}
        brief['self_review'] = [{'lens': 'money', 'status': 'ok'}]
        recorded = self.run_cli('record', run, '--brief', '--task-id', fixer['task_id'], '--input', self.write(brief))
        self.assertNotIn(SELF_REVIEW_MISSING, recorded['warnings'])
        self.assertEqual(recorded['tasks'][-1]['result']['self_review'], brief['self_review'])

    def test_no_plan_or_no_changes_means_no_self_review_warning(self):
        run = self.start()
        _, changed = self.implement(run)
        self.assertNotIn(SELF_REVIEW_MISSING, self.run_cli('record', run, '--dry-run', '--input',
                                                           self.write(changed))['warnings'])
        self.git('checkout', '--', 'app.py', cwd=run['workspace'])
        self.run_cli('record', run, '--input', self.write(changed | {'workspace_dirty': False, 'files_changed': []}))
        self.plan(run)
        task = self.run_cli('task', run, '--role', 'implementer', '--objective', 'nothing', '--write-scope', 'app.py')
        unchanged = self.template(run, task, worker_id='impl-2')
        self.assertEqual(self.run_cli('record', run, '--dry-run', '--input', self.write(unchanged))['warnings'], [])

    # 1b. Second-round gate ----------------------------------------------------------------------------

    def test_fixer_gate_after_two_changes_required_reviews(self):
        run = self.start()
        for worker in ('rev-1', 'rev-2'):
            _, result = self.review(run, 'changes_required', 'Read the full diff', worker)
            self.run_cli('record', run, '--input', self.write(result))
            if worker == 'rev-1':
                # One changes_required round: a fixer needs no confirmation yet.
                first = self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix', '--write-scope', 'app.py',
                                     '--correction-key', 'k1')
                self.assertNotIn('blockers_confirmed', first)
                self.cancel(run, first)
        before = self.state_bytes(run)
        error = self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix again', '--write-scope', 'app.py',
                             '--correction-key', 'k2', ok=False)
        self.assertIn('2 reviews already required changes', error)
        self.assertIn('real blockers and not suggestions', error)
        self.assertIn('--blockers-confirmed', error)
        for bad in ('', ' ', 'two\nlines'):
            self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix again', '--write-scope', 'app.py',
                         '--correction-key', 'k2', '--blockers-confirmed', bad, ok=False)
        self.run_cli('task', run, '--role', 'tester', '--objective', 'test', '--blockers-confirmed', 'x', ok=False)
        self.run_cli('show', run, '--blockers-confirmed', 'x', ok=False)
        self.assertEqual(self.state_bytes(run), before)
        statement = 'Checked F1 and F2: both break invoice totals, not suggestions'
        task = self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix again', '--write-scope', 'app.py',
                            '--correction-key', 'k2', '--blockers-confirmed', statement)
        self.assertEqual(task['blockers_confirmed'], statement)
        saved = self.show(run)
        self.assertEqual(saved['tasks'][-1]['blockers_confirmed'], statement)
        self.assertIn('blockers_confirmed', saved['features'])

    def test_passed_or_incomplete_reviews_do_not_trigger_the_gate(self):
        run = self.start()
        for verdict, worker in (('changes_required', 'rev-1'), ('incomplete', 'rev-2'), ('passed', 'rev-3')):
            _, result = self.review(run, verdict, 'Read the full diff', worker)
            self.run_cli('record', run, '--input', self.write(result))
        self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix', '--write-scope', 'app.py',
                     '--correction-key', 'k1')


if __name__ == '__main__':
    unittest.main()
