import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, state, storage

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.data = self.root / 'data'
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / 'app.py').write_text('def value():\n    return 1\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')
        start = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Change value',
                         '--criterion', 'value returns 2', '--owner', 'session-1', '--runtime', 'codex')
        self.assertEqual(start.returncode, 0, start.stderr)
        self.run = json.loads(start.stdout)
        self.run_id = self.run['run_id']
        self.workspace = Path(self.run['workspace'])

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                               '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')

    def mutate(self, action, *args):
        return self.cli('_run', action, '--run', self.run_id, '--owner', 'session-1', *args)

    def input_file(self, value):
        target = self.root / 'input.json'
        target.write_text(json.dumps(value), encoding='utf-8')
        return str(target)

    def task(self, role='implementer', *extra):
        result = self.mutate('task', '--role', role, '--objective', 'Change value', '--write-scope', 'app.py', *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_feature_revision_bound_end_to_end(self):
        task = self.task()
        (self.workspace / 'app.py').write_text('def value():\n    return 2\n')
        commit = self.cli('_git', 'commit', '--workspace', str(self.workspace), '--path', 'app.py', '--message', 'feature value')
        self.assertEqual(commit.returncode, 0, commit.stderr)
        revision = json.loads(commit.stdout)['revision']
        check = subprocess.run([sys.executable, '-c', 'import app; assert app.value() == 2'],
                               cwd=self.workspace, capture_output=True)
        self.assertEqual(check.returncode, 0)
        # Test imports produce bytecode; remove only the private test's generated artifact.
        import shutil
        if (self.workspace / '__pycache__').exists():
            shutil.rmtree(self.workspace / '__pycache__')
        result = state.empty_result(task, 'implementer-1')
        result.update({'status': 'done', 'summary': 'Changed value', 'result_revision': revision,
                       'files_changed': ['app.py'], 'commits': [revision],
                       'criteria_results': [{'criterion': 'value returns 2', 'status': 'passed', 'revision': revision,
                                             'evidence': 'assert app.value() == 2 passed'}],
                       'validation': [{'name': 'tests', 'procedure': 'assert app.value() == 2', 'status': 'passed',
                                       'revision': revision, 'evidence': 'exit 0'}]})
        recorded = self.mutate('record', '--input', self.input_file(result))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        policy = {'required_checks': ['tests'], 'review_required': True}
        self.assertEqual(self.mutate('update', '--input', self.input_file(policy)).returncode, 0)
        early = self.mutate('close', '--status', 'completed')
        self.assertNotEqual(early.returncode, 0)
        review_task = self.task('reviewer')
        review = state.empty_result(review_task, 'reviewer-2')
        review.update({'status': 'done', 'summary': 'Inspected actual diff', 'review': {'verdict': 'passed'}})
        recorded = self.mutate('record', '--input', self.input_file(review))
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        closed = self.mutate('close', '--status', 'completed')
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(json.loads(closed.stdout)['status'], 'completed')
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertEqual((self.repo / 'app.py').read_text(), 'def value():\n    return 1\n')
        snapshot = state.load(self.data, self.run_id)['config_snapshot']
        self.cli('config', 'set', '--runtime', 'codex', '--role', 'tester', '--model', 'future')
        self.assertEqual(state.load(self.data, self.run_id)['config_snapshot'], snapshot)

    def test_partial_assignment_can_be_replaced_without_losing_history(self):
        original = self.task()
        result = state.empty_result(original, 'worker-a')
        result['summary'] = 'Needs another attempt'
        self.assertEqual(self.mutate('record', '--input', self.input_file(result)).returncode, 0)
        replacement = self.task('fixer', '--replaces', original['task_id'])
        finished = state.empty_result(replacement, 'worker-b')
        finished.update({'status': 'done', 'summary': 'Resolved assignment'})
        result = self.mutate('record', '--input', self.input_file(finished))
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = state.load(self.data, self.run_id)
        self.assertEqual(stored['tasks'][0]['status'], 'done')
        self.assertEqual(stored['tasks'][0]['superseded_by'], replacement['task_id'])
        self.assertEqual(stored['tasks'][0]['result']['status'], 'partial')

    def test_new_coordinator_claims_after_explicit_worker_verification(self):
        update = {'workers': [{'worker_id': 'old-worker', 'status': 'active'}]}
        self.assertEqual(self.mutate('update', '--input', self.input_file(update)).returncode, 0)
        no_confirmation = self.cli('_run', 'claim', '--run', self.run_id, '--owner', 'session-2')
        self.assertNotEqual(no_confirmation.returncode, 0)
        confirmed = self.cli('_run', 'claim', '--run', self.run_id, '--owner', 'session-2', '--workers-confirmed-stopped')
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertEqual(json.loads(confirmed.stdout)['workers'][0]['status'], 'cancelled_confirmed')


if __name__ == '__main__':
    unittest.main()
