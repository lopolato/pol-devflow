import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import checks, state
from devflow.storage import DevFlowError

NOISY_FAILURE = ("import sys\nfor i in range(200): print('line', i)\n"
                 "print('FAILED tests/test_x.py::test_total - AssertionError: 10 != 12')\nsys.exit(3)\n")


class CheckRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.work = self.root / 'work'
        self.work.mkdir()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.work), *args], capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def test_failure_returns_bounded_summary_and_full_log(self):
        result = self.cli('_check', 'run', '--workspace', str(self.work), '--name', 'tests',
                          '--', sys.executable, '-c', NOISY_FAILURE)
        self.assertEqual((result['status'], result['exit_code'], result['lines']), ('failed', 3, 201))
        self.assertEqual(result['failures'], ['FAILED tests/test_x.py::test_total - AssertionError: 10 != 12'])
        self.assertEqual(len(result['tail']), checks.TAIL_LINES)
        log = Path(result['log'])
        self.assertTrue(log.is_relative_to((self.data / 'checks').resolve()))
        text = log.read_text(encoding='utf-8')
        self.assertIn('line 0\n', text)
        self.assertIn('# exit: 3 (failed)', text)

    def test_success_keeps_only_last_lines_and_checked_flags_are_not_parsed(self):
        # -q and --repo belong to the checked command, never to DevFlow.
        result = self.cli('_check', 'run', '--workspace', str(self.work), '--name', 'ok', '--', sys.executable,
                          '-c', 'import sys; print(sys.argv[1:])', '-q', '--repo', 'x')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['tail'], ["['-q', '--repo', 'x']"])
        self.assertEqual(result['failures'], [])

    def test_log_goes_to_the_run_or_lite_folder_and_unknown_ids_fail(self):
        run_dir = self.data / 'runs' / 'run-1'
        run_dir.mkdir(parents=True)
        (run_dir / 'state.json').write_text('{}')
        result = self.cli('_check', 'run', '--workspace', str(self.work), '--name', 'unit', '--run', 'run-1',
                          '--', sys.executable, '-c', 'pass')
        self.assertTrue(Path(result['log']).is_relative_to((run_dir / 'checks').resolve()))
        self.assertIn('Unknown run', self.cli('_check', 'run', '--workspace', str(self.work), '--name', 'x',
                                              '--run', 'missing', '--', sys.executable, '-c', 'pass', ok=False))
        self.assertIn('Unknown lite', self.cli('_check', 'run', '--workspace', str(self.work), '--name', 'x',
                                               '--lite', 'lite-0', '--', sys.executable, '-c', 'pass', ok=False))

    def test_timeout_and_input_validation(self):
        result = checks.run(self.data, self.work, [sys.executable, '-c', 'import time; time.sleep(5)'], 'slow',
                            timeout=1)
        self.assertEqual((result['status'], result['exit_code']), ('timeout', None))
        with self.assertRaises(DevFlowError):
            checks.run(self.data, self.work, [], 'empty')
        with self.assertRaises(DevFlowError):
            checks.run(self.data, self.work, [sys.executable], '../escape')
        self.assertIn('needs the command', self.cli('_check', 'run', '--workspace', str(self.work),
                                                    '--name', 'x', ok=False))

    def test_separator_rejected_outside_check(self):
        self.assertIn('only applies to _check run', self.cli('status', '--', 'echo', ok=False))


class SimplicityLensTests(unittest.TestCase):
    def test_simplicity_is_a_valid_review_lens(self):
        plan = state.validate_review_plan({'lenses': ['requirements', 'simplicity'], 'reason': 'Nueva vista'})
        self.assertEqual(plan['lenses'], ['requirements', 'simplicity'])


if __name__ == '__main__':
    unittest.main()
