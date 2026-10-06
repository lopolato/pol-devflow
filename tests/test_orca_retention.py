import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import orca, storage


class OrcaRetentionTests(unittest.TestCase):
    def setUp(self):
        self.task = {'orca': {'dispatch_id': 'd1', 'settlement': {'outcome': 'succeeded'}}}
        self.run = {'tasks': [self.task]}
        self.value = {
            'dispatch_id': 'd1', 'action': 'retained',
            'retention_source': 'orca', 'user_requested': False,
            'evidence': 'Coordinator verified worker-release receipt and settled Dispatch',
            'orca_release_result': {
                'dispatchId': 'd1', 'state': 'retained',
                'reason': 'user_takeover', 'processAction': 'none',
            },
        }

    def test_runtime_retention_accounts_without_inventing_user_request(self):
        orca.account(self.run, self.task, self.value)
        orca.assert_complete(self.run)
        stored = self.task['orca']['accounting']
        self.assertEqual(stored['action'], 'retained')
        self.assertFalse(stored['user_requested'])
        self.assertEqual(stored['retention_source'], 'orca')
        self.assertEqual(stored['orca_release_result']['processAction'], 'none')

    def test_user_retention_still_requires_explicit_request(self):
        value = {'dispatch_id': 'd1', 'action': 'retained', 'evidence': 'User asked to keep session'}
        with self.assertRaises(storage.DevFlowError):
            orca.account(self.run, self.task, value)
        orca.account(self.run, self.task, value | {'user_requested': True})

    def test_runtime_retention_requires_matching_definitive_receipt(self):
        invalid = [
            {'dispatchId': 'old'}, {'state': 'release_pending'},
            {'state': 'release_unknown'}, {'state': 'released'},
            {'reason': 'identity_unproven'}, {'reason': 'external_terminal'},
            {'processAction': 'closed_agent_terminal'},
        ]
        for change in invalid:
            with self.subTest(change=change):
                value = copy.deepcopy(self.value)
                value['orca_release_result'].update(change)
                with self.assertRaises(storage.DevFlowError):
                    orca.account(self.run, self.task, value)
                self.assertNotIn('accounting', self.task['orca'])

    def test_runtime_retention_rejects_missing_receipt_or_source(self):
        for field in ('orca_release_result', 'retention_source'):
            with self.subTest(field=field):
                value = copy.deepcopy(self.value)
                del value[field]
                with self.assertRaises(storage.DevFlowError):
                    orca.account(self.run, self.task, value)
        for receipt in (None, 'user_takeover', []):
            with self.subTest(receipt=receipt):
                value = self.value | {'orca_release_result': receipt}
                with self.assertRaises(storage.DevFlowError):
                    orca.account(self.run, self.task, value)

    def test_runtime_retention_requires_settlement_and_evidence(self):
        for task, value in (
            ({'orca': {'dispatch_id': 'd1'}}, self.value),
            (self.task, self.value | {'evidence': ''}),
        ):
            with self.subTest(task=task, value=value):
                with self.assertRaises(storage.DevFlowError):
                    orca.account({'tasks': [task]}, task, value)

    def test_runtime_retention_does_not_change_failed_product_outcome(self):
        self.task['orca']['settlement']['outcome'] = 'failed'
        self.task['status'] = 'partial'
        orca.account(self.run, self.task, self.value)
        orca.assert_complete(self.run)
        self.assertEqual(self.task['status'], 'partial')
        self.assertEqual(self.task['orca']['settlement']['outcome'], 'failed')


if __name__ == '__main__':
    unittest.main()
