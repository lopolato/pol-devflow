import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REFUTE_NEEDED = 'Run a refutation (_run task --role reviewer --refute-from ID) before assigning a fixer'
ONLY_INCONCLUSIVE = 'Only inconclusive blockers remain: ask the user to decide'


def blocker(finding_id, location='app.py:1'):
    return {'id': finding_id, 'kind': 'blocker', 'location': location, 'trigger': 'call with empty input',
            'impact': 'wrong total', 'evidence': 'reproduced with a unit test'}


class RefutationTests(unittest.TestCase):
    """Adversarial refutation of review blockers before a fixer (1.0.21)."""

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

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_bytes(self, run):
        return (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()

    def show(self, run):
        return self.run_cli('show', run)['run']

    def template(self, run, task, **fields):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.pop('request_ref')
        result.update({'status': 'done', 'summary': 'done', **fields})
        return result

    def fixer(self, run, *extra, ok=True):
        return self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix', '--write-scope', 'app.py',
                            '--correction-key', 'k1', *extra, ok=ok)

    def reviewed(self, findings=None, plan=None):
        """Run with one committed implementation and a recorded changes_required review."""
        run = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Refutation task', '--criterion', 'c1',
                       '--runtime', 'claude', '--owner', 'co')
        if plan:
            self.run_cli('update', run, '--input', self.write({'review_plan': plan}))
        task = self.run_cli('task', run, '--role', 'implementer', '--objective', 'change', '--write-scope', 'app.py')
        (Path(run['workspace']) / 'app.py').write_bytes(b'changed\n')
        self.run_cli('record', run, '--input', self.write(self.template(
            run, task, worker_id='impl-1', workspace_dirty=True, files_changed=['app.py'])))
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Change')
        review = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        coverage = 'Checked ' + ', '.join((plan or {}).get('lenses', ['the diff']))
        findings = findings if findings is not None else [
            blocker('F1'), blocker('F2'),
            {'id': 'S1', 'kind': 'suggestion', 'location': 'app.py', 'trigger': 't', 'impact': 'i', 'evidence': 'e'}]
        result = self.template(run, review, worker_id='rev-1', findings=findings,
                               review={'verdict': 'changes_required', 'coverage': coverage})
        self.run_cli('record', run, '--input', self.write(result))
        return run, review

    def refute_task(self, run, review):
        return self.run_cli('task', run, '--role', 'reviewer', '--objective', 'refute', '--refute-from',
                            review['task_id'])

    def refutation(self, run, task, outcomes, worker='rev-2', **fields):
        items = [{'finding_id': fid, 'outcome': outcome, 'evidence': f'{outcome} by reading app.py'}
                 for fid, outcome in outcomes.items()]
        return self.template(run, task, worker_id=worker, refutation=items, **fields)

    def test_refute_packet_lists_only_unresolved_blockers_of_that_review(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        self.assertEqual(task['refute']['from_task'], review['task_id'])
        self.assertEqual(task['refute']['findings'], [
            {k: blocker(fid)[k] for k in ('id', 'location', 'trigger', 'impact', 'evidence')} for fid in ('F1', 'F2')])
        self.assertEqual(task['review_diff']['revision'], task['candidate_revision'])
        self.assertIn('refutation', self.show(run)['features'])
        template = self.run_cli('template', run, '--task-id', task['task_id'])
        self.assertEqual(template['refutation'], [{'finding_id': fid, 'outcome': '', 'evidence': ''}
                                                  for fid in ('F1', 'F2')])
        self.assertNotIn('review', template)

    def test_refute_from_needs_a_recorded_review_with_open_blockers(self):
        run, review = self.reviewed(findings=[])
        before = self.state_bytes(run)
        self.assertIn('at least one unresolved blocker', self.run_cli(
            'task', run, '--role', 'reviewer', '--objective', 'refute', '--refute-from', review['task_id'], ok=False))
        for args in (('--role', 'reviewer', '--refute-from', 'missing'),
                     ('--role', 'tester', '--refute-from', review['task_id']),
                     ('--role', 'reviewer', '--refute-from', review['task_id'], '--review-from', review['task_id'])):
            with self.subTest(args=args):
                self.run_cli('task', run, '--objective', 'refute', *args, ok=False)
        self.run_cli('show', run, '--refute-from', review['task_id'], ok=False)
        self.assertEqual(self.state_bytes(run), before)
        # An unrecorded review cannot be refuted either.
        pending = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        self.assertIn('recorded (non-refutation) reviewer', self.run_cli(
            'task', run, '--role', 'reviewer', '--objective', 'refute', '--refute-from', pending['task_id'], ok=False))

    def test_refutation_result_must_cover_exactly_the_listed_ids(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        good = self.refutation(run, task, {'F1': 'corroborated', 'F2': 'refuted'})
        before = self.state_bytes(run)
        entry = good['refutation'][0]
        bad_cases = {
            'missing': [entry],
            'extra': good['refutation'] + [entry | {'finding_id': 'S1'}],
            'duplicate': good['refutation'] + [entry],
            'outcome': [entry | {'outcome': 'maybe'}, good['refutation'][1]],
            'empty evidence': [entry | {'evidence': ' '}, good['refutation'][1]],
            'multiline': [entry | {'evidence': 'a\nb'}, good['refutation'][1]],
            'long': [entry | {'evidence': 'x' * 301}, good['refutation'][1]],
            'extra key': [entry | {'note': 'n'}, good['refutation'][1]],
            'not a list': 'F1',
        }
        for name, items in bad_cases.items():
            with self.subTest(case=name):
                self.run_cli('record', run, '--dry-run', '--input', self.write(good | {'refutation': items}), ok=False)
        self.assertIn('exactly the listed blockers', self.run_cli(
            'validate-result', run, '--input', self.write(good | {'refutation': bad_cases['missing']}), ok=False))
        new = good | {'findings': [blocker('F9')]}
        self.assertIn('must not report new findings', self.run_cli('record', run, '--input', self.write(new), ok=False))
        self.assertIn('Refutation result needs refutation', self.run_cli(
            'record', run, '--input', self.write({k: v for k, v in good.items() if k != 'refutation'}), ok=False))
        self.assertEqual(self.state_bytes(run), before)
        long_ok = [entry | {'evidence': 'x' * 300}, good['refutation'][1]]
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input',
                                     self.write(good | {'refutation': long_ok}))['valid'])
        self.assertTrue(self.run_cli('validate-result', run, '--input', self.write(good))['valid'])

    def test_only_refute_mode_reviewers_report_refutation(self):
        run, review = self.reviewed()
        plain = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review again')
        result = self.template(run, plain, worker_id='rev-2', review={'verdict': 'passed', 'coverage': 'diff'},
                               refutation=[{'finding_id': 'F1', 'outcome': 'refuted', 'evidence': 'e'}])
        self.assertIn('refute-mode', self.run_cli('record', run, '--dry-run', '--input', self.write(result), ok=False))

    def test_refuter_must_be_independent(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        before = self.state_bytes(run)
        for worker in ('impl-1', 'co', 'rev-1'):
            with self.subTest(worker=worker):
                result = self.refutation(run, task, {'F1': 'refuted', 'F2': 'refuted'}, worker=worker)
                for action in (('record', '--dry-run'), ('validate-result',)):
                    error = self.run_cli(action[0], run, *action[1:], '--input', self.write(result), ok=False)
                    self.assertIn('independent reviewer', error)
                brief = {k: result[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                                'observed_revision', 'result_revision', 'refutation')}
                self.assertIn('independent reviewer', self.run_cli(
                    'record', run, '--brief', '--task-id', task['task_id'], '--input', self.write(brief), ok=False))
        self.assertEqual(self.state_bytes(run), before)

    def test_outcomes_are_applied_and_refuted_blockers_count_as_resolved(self):
        plan = {'lenses': ['security', 'money'], 'reason': 'Invoices'}
        run, review = self.reviewed(plan=plan)
        task = self.refute_task(run, review)
        # A refutation needs no lens coverage and no review section; the brief path accepts it too.
        result = self.refutation(run, task, {'F1': 'inconclusive', 'F2': 'refuted'}, worker='rev-2')
        brief = {k: result[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                        'observed_revision', 'result_revision', 'refutation')}
        recorded = self.run_cli('record', run, '--brief', '--task-id', task['task_id'], '--input', self.write(brief))
        findings = {f['id']: f for f in recorded['findings']}
        for fid, outcome in (('F1', 'inconclusive'), ('F2', 'refuted')):
            value = findings[fid]['refutation']
            self.assertEqual({k: value[k] for k in ('outcome', 'evidence', 'by')},
                             {'outcome': outcome, 'evidence': f'{outcome} by reading app.py', 'by': 'rev-2'})
            self.assertIn('at', value)
        self.assertFalse(findings['F1'].get('resolved', False))
        self.assertTrue(findings['F2']['resolved'])
        self.assertEqual(findings['F2']['resolution']['revision'], recorded['current_revision'])
        self.assertEqual(findings['F2']['resolution']['evidence'], 'refuted by reading app.py')
        self.assertNotIn('refutation', findings['S1'])
        # The run-level review stays the original one; a refutation is not a review verdict.
        self.assertEqual(recorded['review']['worker_id'], 'rev-1')
        self.assertEqual(recorded['tasks'][-1]['status'], 'done')
        blockers = self.run_cli('check-close', run)['blockers']
        self.assertIn('Unresolved review blockers remain: F1', blockers)
        self.assertNotIn('Unresolved review blockers remain: F2', blockers)
        self.assertNotIn('Blocker resolution lacks current passing validation', blockers)
        # A new refutation only lists what is still open.
        again = self.refute_task(run, review)
        self.assertEqual([f['id'] for f in again['refute']['findings']], ['F1'])

    def test_fixer_gate_requires_refutation_first(self):
        run, review = self.reviewed()
        before = self.state_bytes(run)
        self.assertIn(REFUTE_NEEDED, self.fixer(run, ok=False))
        for bad in ('', ' ', 'two\nlines'):
            self.fixer(run, '--user-approved', bad, ok=False)
        self.run_cli('task', run, '--role', 'tester', '--objective', 'test', '--user-approved', 'yes', ok=False)
        self.assertEqual(self.state_bytes(run), before)
        statement = 'User asked to fix F1 and F2 without refutation'
        task = self.fixer(run, '--user-approved', statement)
        self.assertEqual(task['user_approved'], statement)
        saved = self.show(run)
        self.assertEqual(saved['tasks'][-1]['user_approved'], statement)
        self.assertIn('user_approved', saved['features'])

    def test_fixer_gate_only_inconclusive_needs_the_user(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        self.run_cli('record', run, '--input', self.write(
            self.refutation(run, task, {'F1': 'inconclusive', 'F2': 'refuted'})))
        self.assertIn(ONLY_INCONCLUSIVE, self.fixer(run, ok=False))
        self.assertEqual(self.fixer(run, '--user-approved', 'User: fix F1 anyway')['user_approved'],
                         'User: fix F1 anyway')

    def test_fixer_gate_allows_corroborated_blockers(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        self.run_cli('record', run, '--input', self.write(
            self.refutation(run, task, {'F1': 'corroborated', 'F2': 'inconclusive'})))
        fixer = self.fixer(run)
        self.assertNotIn('user_approved', fixer)

    def test_fixer_gate_is_off_when_every_blocker_is_refuted_or_absent(self):
        run, review = self.reviewed()
        task = self.refute_task(run, review)
        self.run_cli('record', run, '--input', self.write(
            self.refutation(run, task, {'F1': 'refuted', 'F2': 'refuted'})))
        self.fixer(run)
        clean, _ = self.reviewed(findings=[])
        self.fixer(clean)


if __name__ == '__main__':
    unittest.main()
