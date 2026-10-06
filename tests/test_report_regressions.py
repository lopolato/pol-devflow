import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import config, gitops, package, state, storage


class ReportRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.data = self.root / 'data'
        for args in [('init', '-b', 'feature/test'), ('config', 'user.name', 'Test'),
                     ('config', 'user.email', 'test@example.invalid')]:
            self.git(*args)
        for name in ['a.txt', 'secret.txt', 'with space.txt']:
            (self.repo / name).write_text('original\n')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.run = state.create(self.data, self.repo, 'feature', 'test', config.defaults(),
                                branch='feature/test', revision=self.git('rev-parse', 'HEAD'),
                                criteria=['works'], owner='coordinator')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout.strip()

    def cli(self, action, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'),
                               '--repo', str(self.repo), '--data-dir', str(self.data),
                               '_run', action, '--run', self.run['run_id'], '--owner', 'coordinator',
                               *args], capture_output=True, text=True)

    def input(self, value):
        path = self.root / 'input.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def record_changes(self, declared, committed=False):
        response = self.cli('task', '--role', 'implementer', '--objective', 'edit',
                            '--write-scope', 'a.txt', '--write-scope', 'with space.txt')
        self.assertEqual(response.returncode, 0, response.stderr)
        task = json.loads(response.stdout)
        (self.repo / 'a.txt').write_text('edited\n')
        if committed:
            self.git('add', 'a.txt')
            self.git('commit', '-m', 'edit')
        (self.repo / 'secret.txt').write_text('hidden\n')
        result = state.empty_result(task, 'implementer-1')
        result.update(status='partial', files_changed=declared, workspace_dirty=True,
                      result_revision=self.git('rev-parse', 'HEAD'))
        return self.cli('record', '--input', self.input(result))

    def test_undeclared_dirty_path_rejected(self):
        response = self.record_changes(['a.txt'])
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('changed-file', response.stderr)

    def test_committed_and_dirty_changes_both_checked(self):
        response = self.record_changes(['a.txt'], committed=True)
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('changed-file', response.stderr)

    def test_required_checks_cannot_be_removed(self):
        self.run['required_checks'] = ['tests']
        state.save(self.data, self.run, 'policy')
        response = self.cli('update', '--input', self.input({'required_checks': []}))
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(state.load(self.data, self.run['run_id'])['required_checks'], ['tests'])

    def test_blockers_cannot_be_deleted_or_marked_resolved_by_update(self):
        finding = dict(id='F1', kind='blocker', location='a.txt', trigger='input', impact='wrong', evidence='failure')
        self.run['findings'] = [finding]
        state.save(self.data, self.run, 'blocker')
        for findings in [[], [finding | {'resolved': True}]]:
            with self.subTest(findings=findings):
                response = self.cli('update', '--input', self.input({'findings': findings}))
                self.assertNotEqual(response.returncode, 0)

    def test_resolution_requires_passing_current_validation(self):
        self.run['findings'] = [dict(id='F1', kind='blocker', location='a.txt', trigger='x', impact='y', evidence='z')]
        state.save(self.data, self.run, 'blocker')
        value = dict(finding_id='F1', revision=self.run['current_revision'], evidence='fixed', check='regression')
        response = self.cli('resolve', '--input', self.input(value))
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('passing', response.stderr)
        self.run['validations'] = [dict(name='regression', status='passed', revision=self.run['current_revision'],
                                      procedure='run repro', evidence='repro passes')]
        state.save(self.data, self.run, 'validated')
        response = self.cli('resolve', '--input', self.input(value))
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['findings'][0]['resolution']['check'], 'regression')

    def test_fixer_needs_stable_correction_key(self):
        with self.assertRaisesRegex(storage.DevFlowError, 'correction'):
            state.make_task(self.run, 'fixer', 'fix', ['a.txt'])

    def test_reviewer_receives_full_diff_artifact(self):
        (self.repo / 'a.txt').write_text('review this\n')
        self.git('add', 'a.txt')
        self.git('commit', '-m', 'candidate')
        self.cli('refresh')
        response = self.cli('task', '--role', 'reviewer', '--objective', 'review')
        self.assertEqual(response.returncode, 0, response.stderr)
        task = json.loads(response.stdout)
        self.assertIn('review_diff', task)
        artifact = task['review_diff']
        self.assertIn('+review this', Path(artifact['path']).read_text())
        self.assertEqual(artifact['revision'], self.git('rev-parse', 'HEAD'))
        self.assertEqual(storage.digest(Path(artifact['path']).read_bytes()), artifact['sha256'])

    def test_start_needs_explicit_runtime_before_any_writes(self):
        response = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'),
            '--repo', str(self.repo), '--data-dir', str(self.root / 'new-data'),
            '_run', 'start', '--owner', 'c', '--mode', 'feature', '--request', 'x', '--criterion', 'works'],
            capture_output=True, text=True)
        self.assertNotEqual(response.returncode, 0)
        self.assertFalse((self.root / 'new-data').exists())

    def test_coordinator_cannot_satisfy_independent_review(self):
        self.run['criteria_results'] = [dict(criterion='works', status='passed',
                                            revision=self.run['current_revision'], evidence='works')]
        self.run['review_required'] = True
        self.run['review'] = dict(worker_id='coordinator', verdict='passed', revision=self.run['current_revision'])
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)

    def test_worktree_folder_is_short_even_for_long_description(self):
        info = gitops.prepare(self.repo, 'feature', 'long description ' * 20, self.root / 'worktrees')
        self.assertLessEqual(len(Path(info['workspace']).name), 16)

    def test_staged_only_change_cannot_be_hidden_by_working_copy(self):
        response = self.cli('task', '--role', 'implementer', '--objective', 'edit', '--write-scope', 'a.txt')
        task = json.loads(response.stdout)
        (self.repo / 'secret.txt').write_text('staged hidden\n')
        self.git('add', 'secret.txt')
        (self.repo / 'secret.txt').write_text('original\n')
        result = state.empty_result(task, 'worker')
        result['workspace_dirty'] = True
        response = self.cli('record', '--input', self.input(result))
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('changed-file', response.stderr)

    def test_declared_dirty_paths_with_spaces_and_unicode_are_accepted(self):
        name = ' ñ new file.txt'
        response = self.cli('task', '--role', 'implementer', '--objective', 'edit',
                            '--write-scope', name, '--write-scope', 'with space.txt')
        self.assertEqual(response.returncode, 0, response.stderr)
        task = json.loads(response.stdout)
        (self.repo / name).write_text('new\n')
        (self.repo / 'with space.txt').write_text('changed\n')
        result = state.empty_result(task, 'worker')
        result.update(workspace_dirty=True, files_changed=[name, 'with space.txt'])
        response = self.cli('record', '--input', self.input(result))
        self.assertEqual(response.returncode, 0, response.stderr)

    def test_resolution_is_invalidated_if_its_validation_later_fails(self):
        self.run['criteria_results'] = [dict(criterion='works', status='passed', revision=self.run['current_revision'], evidence='ok')]
        self.run['findings'] = [dict(id='F1', kind='blocker')]
        check = dict(name='repro', status='passed', revision=self.run['current_revision'], procedure='reproduce', evidence='passes')
        self.run['validations'] = [check]
        state.resolve_finding(self.run, dict(finding_id='F1', revision=self.run['current_revision'], evidence='fixed', check='repro'))
        self.run['validations'].append(check | {'status': 'failed', 'evidence': 'fails again'})
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)

    def test_modified_review_diff_cannot_be_recorded(self):
        response = self.cli('task', '--role', 'reviewer', '--objective', 'review')
        task = json.loads(response.stdout)
        Path(task['review_diff']['path']).write_text('tampered')
        result = state.empty_result(task, 'reviewer')
        result.update(status='done', review={'verdict': 'passed'})
        response = self.cli('record', '--input', self.input(result))
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('artifact', response.stderr)

    def test_committed_out_of_scope_path_cannot_be_hidden_by_staged_reversal(self):
        response = self.cli('task', '--role', 'implementer', '--objective', 'edit', '--write-scope', 'a.txt')
        task = json.loads(response.stdout)
        (self.repo / 'secret.txt').write_text('outside scope\n')
        self.git('add', 'secret.txt')
        self.git('commit', '-m', 'hidden committed change')
        (self.repo / 'secret.txt').write_text('original\n')
        self.git('add', 'secret.txt')
        result = state.empty_result(task, 'worker')
        result.update(result_revision=self.git('rev-parse', 'HEAD'), workspace_dirty=True)
        response = self.cli('record', '--input', self.input(result))
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('changed-file', response.stderr)

    def test_failed_validation_cannot_be_erased_from_history(self):
        check = dict(name='repro', status='passed', revision=self.run['current_revision'], procedure='repro', evidence='ok')
        self.run['validations'] = [check, check | {'status': 'failed', 'evidence': 'failed again'}]
        state.save(self.data, self.run, 'checks')
        response = self.cli('update', '--input', self.input({'validations': [check]}))
        self.assertNotEqual(response.returncode, 0)

    def test_runtime_frontmatter_accepts_windows_line_endings(self):
        content = b'---\r\nname: pol-devflow\r\ndescription: test\r\n---\r\nbody\r\n'
        try:
            result = package.skill_for_runtime(content, 'claude')
        except storage.DevFlowError as exc:
            self.fail(str(exc))
        self.assertIn(b'disable-model-invocation: true', result)

    def test_replacement_cannot_reset_its_correction_key(self):
        response = self.cli('task', '--role', 'implementer', '--objective', 'edit', '--write-scope', 'a.txt')
        task = json.loads(response.stdout)
        result = state.empty_result(task, 'worker')
        response = self.cli('record', '--input', self.input(result))
        self.assertEqual(response.returncode, 0, response.stderr)
        response = self.cli('task', '--role', 'fixer', '--objective', 'retry', '--write-scope', 'a.txt',
                            '--replaces', task['task_id'], '--correction-key', 'new-key')
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('key', response.stderr)

    def test_record_role_flag_cannot_turn_implementer_into_reviewer(self):
        response = self.cli('task', '--role', 'implementer', '--objective', 'inspect', '--write-scope', 'a.txt')
        task = json.loads(response.stdout)
        result = state.empty_result(task, 'worker')
        result.update(status='done', review={'verdict': 'passed'})
        response = self.cli('record', '--role', 'reviewer', '--input', self.input(result))
        self.assertNotEqual(response.returncode, 0)
        self.assertIsNone(state.load(self.data, self.run['run_id'])['review'])


if __name__ == '__main__':
    unittest.main()
