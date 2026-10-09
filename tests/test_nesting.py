import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import adapters, config, nesting, state, storage


class NestingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        (self.workspace / 'src').mkdir()
        self.run = {'executor': 'native', 'mode': 'feature', 'workspace': str(self.workspace),
                    'current_revision': 'rev1', 'tasks': [], 'workers': []}
        self.parent = {'task_id': 'parent', 'role': 'tester', 'status': 'pending',
                       'workspace': str(self.workspace), 'candidate_revision': 'rev1',
                       'read_scope': ['src/'], 'write_scope': [], 'depth': 1,
                       'delegation': {'enabled': True}}
        self.run['tasks'].append(self.parent)
        self.run['nesting'] = {'max_workers': 4}

    def test_child_must_be_read_only_and_inside_parent_scope(self):
        valid = nesting.validate_assignment(self.run, 'explorer', [], ['src/'], parent_task_id='parent')
        self.assertEqual(valid['depth'], 2)
        for scope in ('../outside', '/tmp/outside', 'src/../secret'):
            with self.subTest(scope=scope), self.assertRaises(storage.DevFlowError):
                nesting.validate_assignment(self.run, 'explorer', [], [scope], parent_task_id='parent')
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'implementer', [], ['src/'], parent_task_id='parent')
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'tester', ['src/test.py'], ['src/'], parent_task_id='parent')

    def test_no_grant_third_level_or_writer_parent(self):
        self.parent['delegation'] = {'enabled': False}
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'explorer', [], ['src/'], parent_task_id='parent')
        self.parent['delegation'] = {'enabled': True}
        self.parent['depth'] = 2
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'debugger', [], ['src/'], parent_task_id='parent')
        self.parent['depth'] = 1
        self.parent['write_scope'] = ['src/']
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'explorer', [], ['src/'], parent_task_id='parent')

    def test_global_reservation_and_child_slots_are_enforced(self):
        self.run['workers'] = [{'worker_id': f'w{i}', 'status': 'active'} for i in range(4)]
        with self.assertRaisesRegex(storage.DevFlowError, 'reservation limit'):
            nesting.validate_assignment(self.run, 'debugger', [], ['src/'], parent_task_id='parent')
        self.run['workers'] = []
        for i in range(2):
            task_id = f'child{i}'
            grant = nesting.validate_assignment(self.run, 'explorer', [], ['src/'], parent_task_id='parent')
            task = {'task_id': task_id, 'assigned_at': 'now'}
            nesting.apply_assignment(self.run, task, grant)
            task['status'] = 'pending'
            self.run['tasks'].append(task)
        with self.assertRaisesRegex(storage.DevFlowError, 'two child'):
            nesting.validate_assignment(self.run, 'tester', [], ['src/'], parent_task_id='parent')

    def test_parent_cannot_finish_before_children_or_pass_review_with_child_author(self):
        child = {'task_id': 'child', 'parent_task_id': 'parent', 'family_root': 'parent',
                 'status': 'pending', 'result': None}
        self.run['tasks'].append(child)
        result = {'status': 'done', 'review': {'verdict': 'passed'}}
        self.assertTrue(nesting.result_blockers(self.run, self.parent, result))
        self.parent['role'] = 'reviewer'
        child['status'] = 'done'
        child['result'] = {'worker_id': 'helper'}
        self.run['authors'] = ['helper']
        self.assertIn('author', ' '.join(nesting.result_blockers(self.run, self.parent, result)))

    def test_flat_runs_remain_flat_and_claude_profiles_scope_agent(self):
        flat = dict(self.run, nesting=None)
        self.assertIsNone(nesting.validate_assignment(flat, 'implementer', ['src/'], []))
        profiles = adapters.render_all('claude', config.defaults())
        self.assertNotIn('disallowedTools: Agent', profiles['pol-architect.md'])
        self.assertIn('disallowedTools: Agent', profiles['pol-explorer.md'])
        self.assertIn('tools: Read, Glob, Grep, Agent', profiles['pol-reviewer.md'])
        codex = adapters.render_all('codex', config.defaults())
        self.assertIn('sandbox_mode = "read-only"', codex['pol-reviewer.toml'])


if __name__ == '__main__':
    unittest.main()
