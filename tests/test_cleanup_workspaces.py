import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import cleanup, storage


class WorkspaceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.data = self.root / 'data'
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'file').write_text('baseline')
        self.git('add', 'file')
        self.git('commit', '-m', 'baseline')
        self.workspace = self.root / 'orca-workspace'
        self.git('worktree', 'add', '-b', 'feature/summary', str(self.workspace))

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout.strip()

    def register(self):
        return cleanup.register_workspace(self.data, self.repo, {
            'workspace': str(self.workspace), 'branch': 'feature/summary',
            'backend': 'orca', 'worktree_id': 'repo::' + str(self.workspace),
            'evidence': 'Coordinator verified Orca creation receipt', 'orca_command': 'orca'})

    def test_orca_ownership_is_in_preview_and_requires_runtime_check(self):
        self.register()
        item = cleanup.cleanup(self.data, self.repo)['items'][0]
        self.assertEqual(item['worktrees'], [str(self.workspace.resolve())])
        self.assertEqual(item['workspace_backends'], ['orca'])
        result = cleanup.cleanup(self.data, self.repo, apply=True)
        self.assertTrue(result['errors'])
        self.assertTrue(self.workspace.exists())
        self.assertTrue(self.git('branch', '--list', 'feature/summary'))

    def test_orca_removal_is_reconciled_after_transport_error(self):
        self.register()
        def runtime(record, action):
            if action == 'remove':
                self.git('worktree', 'remove', str(self.workspace))
                raise storage.DevFlowError('connection closed')
            return {'exists': self.workspace.exists()}
        with patch('devflow.cleanup._orca_workspace', side_effect=runtime):
            result = cleanup.cleanup(self.data, self.repo, apply=True, orca_idle_confirmed=True)
        self.assertEqual(result['errors'], [])
        self.assertFalse(self.workspace.exists())
        self.assertEqual(result['removed'][0]['removed_worktrees'], [str(self.workspace.resolve())])

    def test_protected_branch_in_owned_workspace_is_preserved(self):
        self.register()
        self.git('switch', '--detach')
        subprocess.run(['git', 'switch', 'main'], cwd=self.workspace, check=True, capture_output=True)
        item = cleanup.cleanup(self.data, self.repo)['items'][0]
        self.assertEqual(item['action'], 'keep')
        self.assertIn('protected branch', ' '.join(item['reasons']))
        self.assertTrue(self.workspace.exists())

    def test_primary_checkout_cannot_be_registered_as_disposable(self):
        with self.assertRaises(storage.DevFlowError):
            cleanup.register_workspace(self.data, self.repo, {
                'workspace': str(self.repo), 'branch': 'main', 'backend': 'orca',
                'worktree_id': 'repo::primary', 'evidence': 'receipt'})

    def test_remote_cleanup_is_opt_in_and_preserves_history(self):
        self.register()
        bare = self.root / 'remote.git'
        self.git('init', '--bare', str(bare))
        self.git('remote', 'add', 'origin', str(bare))
        self.git('push', 'origin', 'main', 'feature/summary')
        self.assertEqual(cleanup.cleanup(self.data, self.repo)['remote'], None)
        item = cleanup.cleanup(self.data, self.repo, remote='origin')['items'][0]
        self.assertTrue(item['remote_branch']['exists'])
        def runtime(record, action):
            if action == 'remove':
                self.git('worktree', 'remove', str(self.workspace))
            return {'exists': self.workspace.exists()}
        with patch('devflow.cleanup._orca_workspace', side_effect=runtime):
            result = cleanup.cleanup(self.data, self.repo, apply=True, remote='origin', orca_idle_confirmed=True)
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['removed'][0]['deleted_remote_branch'])
        self.assertEqual(self.git('ls-remote', '--heads', 'origin', 'refs/heads/feature/summary'), '')
        self.assertTrue((self.data / 'worktrees/.devflow-ownership').exists())

    def test_dirty_workspace_is_kept(self):
        self.register()
        (self.workspace / 'private-untracked').write_text('preserve')
        result = cleanup.cleanup(self.data, self.repo, apply=True, orca_idle_confirmed=True)
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['items'][0]['action'], 'keep')
        self.assertTrue((self.workspace / 'private-untracked').exists())

    def test_orca_can_delete_the_integrated_branch_itself(self):
        self.register()
        def runtime(record, action):
            if action == 'remove':
                self.git('worktree', 'remove', str(self.workspace))
                self.git('branch', '-d', 'feature/summary')
            return {'exists': self.workspace.exists()}
        with patch('devflow.cleanup._orca_workspace', side_effect=runtime):
            result = cleanup.cleanup(self.data, self.repo, apply=True, orca_idle_confirmed=True)
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['removed'][0]['deleted_branch'])
        self.assertEqual(self.git('branch', '--list', 'feature/summary'), '')

    def test_wrong_orca_identity_cannot_remove_git_workspace(self):
        self.register()
        with patch('devflow.cleanup._orca_workspace', return_value={'exists': False}) as runtime:
            result = cleanup.cleanup(self.data, self.repo, apply=True, orca_idle_confirmed=True)
        self.assertTrue(result['errors'])
        self.assertEqual(runtime.call_args.args[1], 'show')
        self.assertTrue(self.workspace.exists())

    def test_unknown_remote_is_rejected_without_mutation(self):
        self.register()
        with self.assertRaises(storage.DevFlowError):
            cleanup.cleanup(self.data, self.repo, apply=True, remote='unknown', orca_idle_confirmed=True)
        self.assertTrue(self.workspace.exists())

    def test_remote_unmerged_revision_prevents_local_and_remote_deletion(self):
        self.register()
        bare = self.root / 'remote.git'
        self.git('init', '--bare', str(bare))
        self.git('remote', 'add', 'origin', str(bare))
        (self.workspace / 'file').write_text('unmerged remote')
        subprocess.run(['git', 'commit', '-am', 'unmerged'], cwd=self.workspace, check=True, capture_output=True)
        self.git('push', 'origin', 'feature/summary')
        item = cleanup.cleanup(self.data, self.repo, remote='origin')['items'][0]
        self.assertEqual(item['action'], 'keep')
        self.assertFalse(item['remote_branch']['merged'])


if __name__ == '__main__':
    unittest.main()
