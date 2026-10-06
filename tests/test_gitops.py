import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import gitops, storage


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_dirty_main_preserved_in_isolated_worktree(self):
        (self.repo / 'app.py').write_text('uncommitted user change\n')
        info = gitops.prepare(self.repo, 'feature', 'Phone', self.root / 'worktrees')
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertEqual((self.repo / 'app.py').read_text(), 'uncommitted user change\n')
        self.assertEqual((Path(info['workspace']) / 'app.py').read_text(), 'original\n')
        self.assertTrue(info['branch'].startswith('feature/'))

    def test_commit_refuses_main_and_unrelated_staging(self):
        (self.repo / 'new.py').write_text('x\n')
        with self.assertRaises(storage.DevFlowError):
            gitops.commit(self.repo, ['new.py'], 'change')
        self.git('switch', '-c', 'feature/new')
        (self.repo / 'unrelated.py').write_text('y\n')
        self.git('add', 'unrelated.py')
        with self.assertRaises(storage.DevFlowError):
            gitops.commit(self.repo, ['new.py'], 'change')
        self.assertEqual(self.git('diff', '--cached', '--name-only'), 'unrelated.py')

    def test_commit_accepts_crlf_but_rejects_real_whitespace_errors(self):
        self.git('config', 'core.autocrlf', 'false')
        self.git('switch', '-c', 'fix/crlf')
        (self.repo / 'windows.txt').write_bytes(b'first\r\nsecond\r\n')
        revision = gitops.commit(self.repo, ['windows.txt'], 'CRLF file')
        self.assertEqual(self.git('rev-parse', 'HEAD'), revision)
        (self.repo / 'bad.txt').write_bytes(b'trailing   \n')
        with self.assertRaises(storage.DevFlowError) as error:
            gitops.commit(self.repo, ['bad.txt'], 'whitespace')
        self.assertIn('trailing whitespace', str(error.exception))
        (self.repo / 'bad.txt').write_bytes(b'<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n')
        with self.assertRaises(storage.DevFlowError) as error:
            gitops.commit(self.repo, ['bad.txt'], 'conflict markers')
        self.assertIn('conflict marker', str(error.exception))

    def test_explicit_commit_and_revision(self):
        self.git('switch', '-c', 'feature/new')
        (self.repo / 'new.py').write_text('x\n')
        revision = gitops.commit(self.repo, ['new.py'], 'change')
        self.assertEqual(revision, self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_commit_rejects_paths_outside_repo(self):
        self.git('switch', '-c', 'feature/new')
        with self.assertRaises(storage.DevFlowError):
            gitops.commit(self.repo, ['../secret'], 'bad')


if __name__ == '__main__':
    unittest.main()
