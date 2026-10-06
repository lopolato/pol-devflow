import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, state, storage


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.repo = self.data / 'repo'
        self.repo.mkdir()
        self.run = state.create(self.data, self.repo, 'feature', 'Add a phone', config.defaults(),
                                branch='feature/phone', revision='abc', criteria=['phone works'])

    def test_snapshot_and_status_read_only(self):
        before = {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()}
        info = state.status(self.data, run_id=self.run['run_id'], verify_git=False)
        self.assertEqual(info['run']['config_snapshot'], config.defaults())
        after = {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_locks_exclude_another_coordinator(self):
        with state.RunLock(self.data, self.run['run_id'], 'one'):
            with self.assertRaises(storage.DevFlowError):
                with state.RunLock(self.data, self.run['run_id'], 'two'):
                    pass

    def test_task_result_rejects_wrong_identity_and_scope(self):
        task = state.make_task(self.run, 'implementer', 'Add phone', ['customer.py'])
        result = state.empty_result(task, 'worker-1')
        result['run_id'] = 'wrong'
        with self.assertRaises(storage.DevFlowError):
            state.validate_result(task, result)
        result['run_id'] = task['run_id']
        result['files_changed'] = ['outside.py']
        with self.assertRaises(storage.DevFlowError):
            state.validate_result(task, result)

    def test_stale_validation_and_self_review_cannot_complete(self):
        run = copy.deepcopy(self.run)
        run['current_revision'] = 'def'
        run['criteria_results'] = [{'criterion': 'phone works', 'status': 'passed', 'revision': 'def',
                                   'evidence': 'phone scenario passed'}]
        run['required_checks'] = ['tests']
        run['validations'] = [{'name': 'tests', 'status': 'passed', 'revision': 'abc',
                               'procedure': 'python -m unittest', 'evidence': '3 tests passed'}]
        run['review_required'] = True
        run['authors'] = ['worker-1']
        run['review'] = {'verdict': 'passed', 'revision': 'def', 'worker_id': 'worker-1'}
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(run)
        run['validations'][0]['revision'] = 'def'
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(run)
        run['review']['worker_id'] = 'worker-2'
        state.assert_complete(run)

    def test_fix_limit_and_no_new_evidence(self):
        run = copy.deepcopy(self.run)
        state.record_attempt(run, 'task', 'same failure', 'first evidence')
        with self.assertRaises(storage.DevFlowError):
            state.record_attempt(run, 'task', 'same failure', 'first evidence')
        state.record_attempt(run, 'task', 'different failure', 'second evidence')
        state.record_attempt(run, 'task', 'third failure', 'third evidence')
        with self.assertRaises(storage.DevFlowError):
            state.record_attempt(run, 'task', 'fourth', 'fourth')

    def test_ambiguous_status_lists_candidates(self):
        state.create(self.data, self.repo, 'error', 'Fix login', config.defaults(), branch='fix/login', revision='abc', criteria=['login works'])
        info = state.status(self.data, repository=self.repo, verify_git=False)
        self.assertEqual(len(info['candidates']), 2)
        self.assertNotIn('run', info)

    def test_traversal_run_id_rejected(self):
        with self.assertRaises(storage.DevFlowError):
            state.load(self.data, '../outside')


if __name__ == '__main__':
    unittest.main()
