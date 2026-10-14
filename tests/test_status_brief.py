import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BRIEF_KEYS = {'run_id', 'mode', 'status', 'phase', 'branch', 'current_revision', 'workspace', 'next_action',
              'review_lenses', 'open_tasks', 'open_blockers', 'counts', 'budget', 'request_ref'}


class StatusBriefTests(unittest.TestCase):
    """Compact status for context recovery after a compaction (1.0.21)."""

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

    def raw(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                               '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')

    def cli(self, *args, ok=True):
        result = self.raw(*args)
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

    def start(self, request='Brief status task'):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', request, '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co')

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def template(self, run, task, **fields):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.pop('request_ref')
        result.update({'status': 'done', 'summary': 'done', **fields})
        return result

    def busy_run(self):
        """Run with a plan, a recorded review with blockers, a refutation and an open task."""
        run = self.start()
        self.run_cli('update', run, '--input', self.write({
            'review_plan': {'lenses': ['security', 'money'], 'reason': 'Invoices'},
            'next_action': 'Assign the fixer for F1'}))
        review = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        blockers = [{'id': fid, 'kind': 'blocker', 'location': 'app.py:1', 'trigger': 't', 'impact': 'i',
                     'evidence': 'e'} for fid in ('F1', 'F2')]
        self.run_cli('record', run, '--input', self.write(self.template(
            run, review, worker_id='rev-1', findings=blockers,
            review={'verdict': 'changes_required', 'coverage': 'security and money checked'})))
        refute = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'refute', '--refute-from',
                              review['task_id'])
        self.run_cli('record', run, '--input', self.write(self.template(run, refute, worker_id='rev-2', refutation=[
            {'finding_id': 'F1', 'outcome': 'corroborated', 'evidence': 'Reproduced'},
            {'finding_id': 'F2', 'outcome': 'refuted', 'evidence': 'Guarded'}])))
        explorer = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map the invoice module')
        return run, review, explorer

    def test_brief_shape_without_packets_or_results(self):
        run, review, explorer = self.busy_run()
        output = self.raw('status', '--brief', '--run', run['run_id'])
        self.assertEqual(output.returncode, 0, output.stderr)
        value = json.loads(output.stdout)
        self.assertEqual(set(value), BRIEF_KEYS)
        self.assertEqual(value['run_id'], run['run_id'])
        self.assertEqual((value['mode'], value['status']), ('feature', 'active'))
        self.assertEqual(value['branch'], run['branch'])
        self.assertEqual(len(value['current_revision']), 12)
        self.assertTrue(run['current_revision'].startswith(value['current_revision']))
        self.assertEqual(value['workspace'], run['workspace'])
        self.assertEqual(value['next_action'], 'Assign the fixer for F1')
        self.assertEqual(value['review_lenses'], ['security', 'money'])
        self.assertEqual(value['open_tasks'], [{'task_id': explorer['task_id'], 'role': 'explorer',
                                                'status': 'pending'}])
        self.assertEqual(value['open_blockers'], [{'id': 'F1', 'location': 'app.py:1', 'refutation': 'corroborated'}])
        self.assertEqual(value['counts'], {'reviews': 1, 'refutations': 1, 'changes_required': 1, 'fixers': 0})
        self.assertEqual(value['budget']['workers_used'], 3)
        self.assertEqual(value['request_ref'], run['request_ref']['path'])
        # No task packets, objectives, results or artifacts leak into the brief.
        for leak in ('map the invoice module', 'review_diff', 'coverage', 'Reproduced', 'objective', 'summary'):
            self.assertNotIn(leak, output.stdout)
        self.assertLessEqual(len(output.stdout.splitlines()), 40)
        shown = self.raw('_run', 'show', '--run', run['run_id'], '--brief')
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout), value)

    def test_brief_size_is_bounded(self):
        run = self.start()
        long_text = 'x' * 1000
        self.run_cli('update', run, '--input', self.write({'next_action': long_text, 'findings': [
            {'id': f'F{i}', 'kind': 'blocker', 'location': f'app.py:{i}', 'trigger': 't', 'impact': 'i',
             'evidence': 'e'} for i in range(12)]}))
        for index in range(12):
            self.run_cli('task', run, '--role', 'explorer', '--objective', f'map part {index} ' + 'y' * 200)
        output = self.raw('status', '--brief', '--run', run['run_id'])
        self.assertEqual(output.returncode, 0, output.stderr)
        value = json.loads(output.stdout)
        self.assertLessEqual(len(output.stdout.splitlines()), 40)
        self.assertLess(len(output.stdout), 4000)
        self.assertEqual(len(value['open_tasks']), 8)
        self.assertEqual(value['open_tasks_more'], 4)
        self.assertEqual(len(value['open_blockers']), 8)
        self.assertEqual(value['open_blockers_more'], 4)
        self.assertLessEqual(len(value['next_action']), 300)
        self.assertNotIn('y' * 50, output.stdout)
        full = self.raw('status', '--run', run['run_id'])
        self.assertGreater(len(full.stdout), 4 * len(output.stdout))

    def test_brief_without_run_lists_candidates_compactly(self):
        first = self.start('First brief task')
        # One run in the repository: the brief of that run.
        self.assertEqual(self.cli('status', '--brief')['run_id'], first['run_id'])
        second = self.start('Second brief task')
        output = self.raw('status', '--brief')
        self.assertEqual(output.returncode, 0, output.stderr)
        value = json.loads(output.stdout)
        self.assertEqual({c['run_id'] for c in value['candidates']}, {first['run_id'], second['run_id']})
        for candidate in value['candidates']:
            self.assertEqual(set(candidate), {'run_id', 'mode', 'status', 'phase', 'updated_at'})
        self.assertEqual(value['stale_runs'], 0)
        self.assertIn('--run', value['message'])
        self.assertNotIn('tasks', output.stdout)
        self.assertLessEqual(len(output.stdout.splitlines()), 40)

    def test_brief_flag_scope(self):
        run = self.start()
        self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--brief', ok=False)
        self.run_cli('update', run, '--input', self.write({'phase': 'x'}), '--brief', ok=False)
        self.assertEqual(self.cli('status', '--run', run['run_id'])['run']['run_id'], run['run_id'])
        self.assertIn('--brief', self.raw('help', 'status').stdout)


if __name__ == '__main__':
    unittest.main()
