import sys
import json
import subprocess
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

    def test_each_child_can_finish_while_its_sibling_is_pending(self):
        children = [{'task_id': name, 'parent_task_id': 'parent', 'depth': 2,
                     'role': 'explorer', 'write_scope': [], 'delegation': {'enabled': False},
                     'status': 'pending'} for name in ('first', 'second')]
        self.run['tasks'].extend(children)
        self.assertEqual(nesting.result_blockers(self.run, children[0], {'status': 'done'}), [])
        self.assertTrue(nesting.result_blockers(self.run, self.parent, {'status': 'done'}))
        children[0]['status'] = 'done'
        self.assertEqual(nesting.result_blockers(self.run, children[1], {'status': 'done'}), [])
        children[1]['status'] = 'done'
        self.assertEqual(nesting.result_blockers(self.run, self.parent, {'status': 'done'}), [])

    def test_capacity_counts_union_and_cannot_be_bypassed_by_flat_task(self):
        self.run['tasks'].append({'task_id': 'pending', 'status': 'pending'})
        self.run['workers'] = [{'worker_id': 'w1', 'task_id': 'finished1', 'status': 'active'},
                               {'worker_id': 'w2', 'task_id': 'finished2', 'status': 'active'}]
        with self.assertRaises(storage.DevFlowError):
            nesting.validate_assignment(self.run, 'explorer', [], ['src/'])
        self.run['workers'] = [{'worker_id': 'parent-worker', 'task_id': 'parent', 'status': 'active'}]
        self.assertIsNone(nesting.validate_assignment(self.run, 'explorer', [], ['src/']))

    def test_directory_annotation_cannot_expand_exact_scope(self):
        self.assertFalse(nesting.scope_contains(self.workspace, 'src', self.workspace, 'src/'))
        self.assertTrue(nesting.scope_contains(self.workspace, 'src/', self.workspace, 'src/'))

    def test_parent_rejects_completed_child_with_running_native_worker(self):
        self.run['tasks'].append({'task_id': 'child', 'parent_task_id': 'parent', 'status': 'done',
                                 'result': {'worker_id': 'native-child'}})
        self.run['workers'] = [{'worker_id': 'native-child', 'task_id': 'child', 'status': 'active'}]
        self.assertTrue(nesting.result_blockers(self.run, self.parent, {'status': 'done'}))

    def test_orca_and_missing_preflight_rejected(self):
        for executor in ('native', 'orca'):
            self.run['executor'] = executor
            with self.assertRaises(storage.DevFlowError):
                nesting.validate_assignment(self.run, 'tester', [], ['src/'], can_delegate=True,
                                            native_max_workers=4)


class NestedCliTests(unittest.TestCase):
    def test_register_children_individually_then_parent_and_reject_leaf_verdict(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'; repo.mkdir()
            for args in [('init', '-b', 'main'), ('config', 'user.name', 'Test'),
                         ('config', 'user.email', 'test@example.invalid')]:
                subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
            (repo / 'sample.txt').write_text('sample\n', encoding='utf-8')
            subprocess.run(['git', 'add', 'sample.txt'], cwd=repo, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'initial'], cwd=repo, check=True, capture_output=True)
            data = Path(tmp) / 'data'
            def call(*args, ok=True):
                proc = subprocess.run([sys.executable, '-B', str(root / 'scripts/devflow.py'),
                                       '--repo', str(repo), '--data-dir', str(data), *args],
                                      capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(proc.returncode == 0, ok, proc.stderr)
                return json.loads(proc.stdout) if ok else proc.stderr
            run = call('_run', 'start', '--mode', 'feature', '--request', 'Probe', '--criterion', 'read',
                       '--runtime', 'codex', '--owner', 'root')
            def mutate(action, *args, **kwargs):
                return call('_run', action, '--run', run['run_id'], '--owner', 'root', *args, **kwargs)
            parent = mutate('task', '--role', 'tester', '--objective', 'Read together', '--read-scope', './',
                            '--can-delegate', '--native-nesting-evidence', 'fixture declared capability',
                            '--native-max-workers', '4')
            children = [mutate('task', '--role', 'explorer', '--objective', 'Read sample',
                               '--read-scope', 'sample.txt', '--parent-task', parent['task_id']) for _ in range(2)]
            result_file = Path(tmp) / 'result.json'
            def report(task, worker):
                value = state.empty_result(task, worker)
                value.update(status='done', summary='Read sample', result_revision=run['current_revision'])
                return value
            parent_result = report(parent, 'parent-worker')
            result_file.write_text(json.dumps(parent_result), encoding='utf-8')
            mutate('record', '--input', str(result_file), '--dry-run', ok=False)
            bad = report(children[0], 'child-first'); bad['review'] = {'verdict': 'passed'}
            result_file.write_text(json.dumps(bad), encoding='utf-8')
            mutate('validate-result', '--input', str(result_file), ok=False)
            for index, child in enumerate(children):
                result_file.write_text(json.dumps(report(child, f'child-{index}')), encoding='utf-8')
                mutate('validate-result', '--input', str(result_file))
                mutate('record', '--input', str(result_file))
            parent_result['subdelegation_trace'] = {'child_task_ids': [c['task_id'] for c in children],
                                                   'summary': 'Both returned independently'}
            result_file.write_text(json.dumps(parent_result), encoding='utf-8')
            mutate('record', '--input', str(result_file))
            self.assertEqual(call('_run', 'show', '--run', run['run_id'])['delegation_tree']['roots'][0]['status'], 'done')


if __name__ == '__main__':
    unittest.main()
