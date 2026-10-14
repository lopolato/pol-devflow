import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PythonEnvProfileTests(unittest.TestCase):
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
        (self.repo / '.gitignore').write_text('.venv/\nbackend/.venv/\n')
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', '.gitignore', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def venv(self, relative, home):
        folder = self.repo / relative
        (folder / 'Scripts').mkdir(parents=True)
        (folder / 'bin').mkdir()
        (folder / 'Scripts' / 'python.exe').write_text('')
        (folder / 'bin' / 'python').write_text('')
        (folder / 'pyvenv.cfg').write_text(f'home = {home}\nversion = 3.11.9\n')

    def python(self, repo):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(repo), '_profile', 'show'], capture_output=True, text=True,
                                encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['python']

    def test_no_virtual_environment(self):
        self.assertIsNone(self.python(self.repo))
        self.assertFalse(self.data.exists())

    def test_root_venv_preferred_and_others_listed(self):
        self.venv('backend/.venv', r'C:\Python311')
        self.venv('.venv', r'C:\Users\x\AppData\Local\Programs\Python\Python311')
        env = self.python(self.repo)
        self.assertEqual(env['venv'], '.venv')
        self.assertTrue(env['exists'])
        self.assertFalse(env['store_base'])
        self.assertNotIn('warning', env)
        self.assertEqual(env['others'], ['backend/.venv'])

    def test_store_based_venv_warns_and_subfolder_is_found_from_worktree(self):
        self.venv('backend/.venv', r'C:\Users\x\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11')
        worktree = self.root / 'wt'
        self.git('worktree', 'add', '-q', '-b', 'feature/x', str(worktree))
        env = self.python(worktree)
        self.assertEqual(env['venv'], 'backend/.venv')
        self.assertTrue(env['store_base'])
        self.assertIn('Microsoft Store', env['warning'])
        self.assertTrue(Path(env['python']).is_relative_to(self.repo.resolve()))


if __name__ == '__main__':
    unittest.main()
