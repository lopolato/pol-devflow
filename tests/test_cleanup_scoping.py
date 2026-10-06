import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CleanupScopingTests(unittest.TestCase):
    """The data dir is shared by every repository: cleanup must only list this repository's items."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.a, self.b = self.make_repo('repo-a'), self.make_repo('repo-b')

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'Test'),
                     ('config', 'user.email', 'test@example.invalid')):
            self.git(repo, *args)
        (repo / 'app.py').write_text('original\n')
        self.git(repo, 'add', 'app.py')
        self.git(repo, 'commit', '-m', 'initial')
        return repo

    def git(self, repo, *args):
        return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, repo, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(repo), *args], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def start(self, repo, request='tarea'):
        return self.cli(repo, '_run', 'start', '--mode', 'feature', '--request', request, '--criterion', 'c',
                        '--runtime', 'claude', '--owner', 'co')

    def branches(self, repo, *args):
        return {item['branch']: item for item in self.cli(repo, 'cleanup', *args)['items']}

    def test_full_worktree_of_another_repository_is_not_listed(self):
        run = self.start(self.b, 'tarea de B')
        self.assertIn('git_common_dir', json.loads(
            next((self.data / 'worktrees/.devflow-ownership').glob('*.json')).read_text()))
        self.assertNotIn(run['branch'], self.branches(self.a))
        self.assertIn(run['branch'], self.branches(self.b))
        self.cli(self.a, 'cleanup', '--apply', '--purge-history')
        self.assertTrue(Path(run['workspace']).exists())
        self.assertTrue(self.git(self.b, 'branch', '--list', run['branch']))

    def test_cleanup_from_linked_worktree_finds_repository_records(self):
        run = self.start(self.a)
        linked = self.root / 'linked'
        self.git(self.a, 'worktree', 'add', '-b', 'side', str(linked))
        lite = self.cli(linked, '_lite', 'start', '--mode', 'feature', '--request', 'lite in linked')
        items = self.branches(linked)
        self.assertIn(run['branch'], items)
        self.assertEqual(items[run['branch']]['worktrees'], [str(Path(run['workspace']).resolve())])
        self.assertIn(lite['branch'], items)
        # The linked checkout disappears but its lite branch remains in the repository.
        self.git(self.a, 'worktree', 'remove', str(linked))
        items = self.branches(self.a)
        self.assertIn(lite['branch'], items)
        self.assertIn(run['branch'], items)

    def test_legacy_ownership_record_matches_only_registered_worktrees(self):
        own, foreign = self.root / 'own-wt', self.root / 'foreign-wt'
        self.git(self.a, 'worktree', 'add', '-b', 'feature/legacy-own', str(own))
        self.git(self.b, 'worktree', 'add', '-b', 'feature/legacy-foreign', str(foreign))
        owners = self.data / 'worktrees/.devflow-ownership'
        owners.mkdir(parents=True)
        for name, workspace, branch in (('own', own, 'feature/legacy-own'),
                                        ('foreign', foreign, 'feature/legacy-foreign')):
            (owners / (name + '.json')).write_text(json.dumps({
                'schema_version': 1, 'kind': 'root', 'workspace': str(workspace.resolve()), 'branch': branch}))
        items = self.branches(self.a)
        self.assertIn('feature/legacy-own', items)
        self.assertNotIn('feature/legacy-foreign', items)
        self.assertIn('feature/legacy-foreign', self.branches(self.b))

    def test_history_only_items_are_summarized_until_purge_history(self):
        lite = self.cli(self.a, '_lite', 'start', '--mode', 'feature', '--request', 'gone')
        self.git(self.a, 'switch', 'main')
        self.git(self.a, 'branch', '-D', lite['branch'])
        result = self.cli(self.a, 'cleanup')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['history_retained'], {'count': 1, 'branches': [lite['branch']]})
        self.assertIn('--purge-history', result['next_action'])
        self.assertEqual(self.cli(self.a, 'cleanup', '--apply')['removed'], [])
        self.assertTrue((self.data / 'lite' / (lite['id'] + '.json')).exists())
        purge = self.cli(self.a, 'cleanup', '--purge-history')
        self.assertEqual([(i['branch'], i['action']) for i in purge['items']], [(lite['branch'], 'forget')])
        self.assertEqual(purge['history_retained']['count'], 0)
        applied = self.cli(self.a, 'cleanup', '--apply', '--purge-history')
        self.assertEqual([r['branch'] for r in applied['removed']], [lite['branch']])
        self.assertFalse((self.data / 'lite' / (lite['id'] + '.json')).exists())
        self.assertEqual(self.cli(self.a, 'cleanup')['history_retained']['count'], 0)

    def test_gone_branch_with_real_blocker_is_still_listed(self):
        run = self.start(self.a)
        self.git(self.a, 'worktree', 'remove', run['workspace'])
        self.git(self.a, 'branch', '-D', run['branch'])
        result = self.cli(self.a, 'cleanup')
        item = {i['branch']: i for i in result['items']}[run['branch']]
        self.assertEqual(item['action'], 'keep')
        self.assertIn('run still active', ' '.join(item['reasons']))
        self.assertEqual(result['history_retained']['count'], 0)

    def test_gone_local_branch_with_remote_branch_is_listed_for_remote_cleanup(self):
        bare = self.root / 'remote.git'
        self.git(self.root, 'init', '--bare', str(bare))
        self.git(self.a, 'remote', 'add', 'origin', str(bare))
        lite = self.cli(self.a, '_lite', 'start', '--mode', 'feature', '--request', 'pushed')
        self.git(self.a, 'push', 'origin', 'main', lite['branch'])
        self.git(self.a, 'switch', 'main')
        self.git(self.a, 'branch', '-D', lite['branch'])
        self.assertEqual(self.cli(self.a, 'cleanup')['history_retained']['branches'], [lite['branch']])
        item = self.branches(self.a, '--remote', 'origin')[lite['branch']]
        self.assertEqual(item['action'], 'remove_remote')
        applied = self.cli(self.a, 'cleanup', '--apply', '--remote', 'origin')
        self.assertTrue(applied['removed'][0]['deleted_remote_branch'])
        self.assertEqual(self.git(self.a, 'ls-remote', '--heads', 'origin', 'refs/heads/' + lite['branch']), '')


if __name__ == '__main__':
    unittest.main()
