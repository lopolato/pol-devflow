import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, gitops, package, state, storage


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_criterion_without_evidence_cannot_complete(self):
        run = state.create(self.root / 'data', self.root, 'feature', 'Feature', config.defaults(),
                           branch='feature/test', revision='abc', criteria=['works'])
        run['criteria_results'] = [{'criterion': 'works', 'status': 'passed', 'revision': 'abc'}]
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(run)

    def test_task_packet_reports_actual_remaining_recovery_budget(self):
        run = state.create(self.root / 'data', self.root, 'error', 'Fix', config.defaults(),
                           branch='fix/test', revision='abc', criteria=['works'])
        state.record_attempt(run, 'issue', 'first', 'evidence1')
        state.record_attempt(run, 'issue', 'second', 'evidence2')
        task = state.make_task(run, 'fixer', 'Fix issue', ['app.py'], task_id='issue', correction_key='issue')
        self.assertEqual(task['remaining_fix_cycles'], 1)
        state.record_attempt(run, 'issue', 'third', 'evidence3')
        with self.assertRaises(storage.DevFlowError):
            state.make_task(run, 'fixer', 'Fix issue', ['app.py'], task_id='issue', correction_key='issue')

    def test_cleanup_cannot_remove_another_runs_root_worktree(self):
        repo = self.root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        git('init', '-b', 'main')
        git('config', 'user.name', 'DevFlow Test')
        git('config', 'user.email', 'devflow@example.invalid')
        (repo / 'app.py').write_text('x\n')
        git('add', 'app.py')
        git('commit', '-m', 'base')
        a = gitops.prepare(repo, 'feature', 'run-a', self.root / 'trees')
        b = gitops.prepare(repo, 'feature', 'run-b', self.root / 'trees')
        with self.assertRaises(storage.DevFlowError):
            gitops.remove_integrated_child(a['workspace'], b['workspace'])
        self.assertTrue(Path(b['workspace']).exists())

    def test_generated_symlink_cannot_overwrite_its_unowned_target(self):
        data, home = self.root / 'data', self.root / 'codex'
        package.install(data, 'codex', home)
        generated = home / 'agents/pol-reviewer.toml'
        user_file = home / 'agents/user-owned.toml'
        user_file.write_bytes(generated.read_bytes())
        generated.unlink()
        try:
            generated.symlink_to(user_file)
        except OSError:
            self.skipTest('Host does not permit symlink creation')
        before = user_file.read_bytes()
        cfg_before = (data / 'config/models.yaml').read_bytes()
        with self.assertRaises(storage.DevFlowError):
            package.config_set(data, 'codex', 'reviewer', model='other')
        self.assertEqual(user_file.read_bytes(), before)
        self.assertEqual((data / 'config/models.yaml').read_bytes(), cfg_before)

    def test_status_does_not_call_old_validation_current(self):
        repo = self.root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        git('init', '-b', 'feature/test')
        git('config', 'user.name', 'DevFlow Test')
        git('config', 'user.email', 'devflow@example.invalid')
        git('commit', '--allow-empty', '-m', 'old')
        old = git('rev-parse', 'HEAD')
        git('commit', '--allow-empty', '-m', 'new')
        new = git('rev-parse', 'HEAD')
        data = self.root / 'data'
        run = state.create(data, repo, 'feature', 'Feature', config.defaults(),
                           branch='feature/test', revision=new, criteria=['works'])
        run['validations'] = [{'name': 'tests', 'status': 'passed', 'revision': old,
                              'procedure': 'tests', 'evidence': 'exit 0'}]
        state.save(data, run, 'validation recorded')
        info = state.status(data, run_id=run['run_id'])
        self.assertFalse(info['evidence_current'])


if __name__ == '__main__':
    unittest.main()
