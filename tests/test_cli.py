import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                               '--repo', str(self.root), *args], capture_output=True, text=True, encoding='utf-8')

    def test_help_and_plan_only_do_not_create_data(self):
        result = self.run_cli('help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('error', 'feature', 'optimize', 'help', 'status', 'config'):
            self.assertIn(command, result.stdout)
        result = self.run_cli('feature', '--plan-only', 'Add phone')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['plan_only'])
        self.assertFalse(self.data.exists())

    def test_status_without_runs_read_only(self):
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['candidates'], [])
        self.assertFalse(self.data.exists())

    def test_config_show_and_validate_read_only(self):
        for action in ('show', 'validate'):
            result = self.run_cli('config', action)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())

    def test_config_set_and_invalid_arguments(self):
        result = self.run_cli('config', 'set', '--runtime', 'codex', '--role', 'reviewer', '--model', 'example')
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (self.data / 'config/models.yaml').read_bytes()
        result = self.run_cli('config', 'set', '--runtime', 'codex', '--role', 'coordinator', '--model', 'x')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.data / 'config/models.yaml').read_bytes(), before)

    def test_unknown_command_does_not_start_run(self):
        result = self.run_cli('unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.data.exists())


if __name__ == '__main__':
    unittest.main()
