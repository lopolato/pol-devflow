import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CodegraphProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(*args)
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def show(self, repo):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(repo), '_profile', 'show'], capture_output=True, text=True,
                                encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['codegraph']

    def test_no_index_reports_none(self):
        self.assertIsNone(self.show(self.repo))

    def test_index_found_from_linked_worktree_and_ignore_status(self):
        (self.repo / '.codegraph').mkdir()
        # Config-only folder (like ~/.codegraph) is not an index.
        self.assertIsNone(self.show(self.repo))
        (self.repo / '.codegraph/codegraph.db').write_text('x')
        index = self.show(self.repo)
        self.assertEqual(Path(index['project_path']).resolve(), self.repo.resolve())
        self.assertFalse(index['ignored_by_git'])
        (self.repo / '.git/info/exclude').write_text('.codegraph/\n')
        self.assertTrue(self.show(self.repo)['ignored_by_git'])
        # A task worktree has no index of its own: the profile points back to the main checkout.
        worktree = self.root / 'wt'
        self.git('worktree', 'add', '-q', '-b', 'feature/x', str(worktree))
        self.assertFalse((worktree / '.codegraph').exists())
        self.assertEqual(Path(self.show(worktree)['project_path']).resolve(), self.repo.resolve())
        self.assertFalse(self.data.exists())


if __name__ == '__main__':
    unittest.main()
