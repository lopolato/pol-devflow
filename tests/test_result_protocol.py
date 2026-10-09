import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import cli, config, orca, state, storage


class ResultProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.run = state.create(self.data, self.data, 'feature', 'Do it', config.defaults(),
                                'feature/example', 'abc', ['works'])
        self.task = state.make_task(self.run, 'implementer', 'Do it', [])
        self.run['tasks'].append(self.task)
        state.save(self.data, self.run, 'task assigned')
        self.result = state.empty_result(self.task, 'worker-id')

    def test_preflight_read_only_before_settlement_preserves_claims(self):
        self.result['status'] = 'blocked'
        self.result['findings'] = [{'kind': 'blocker', 'location': 'file:1', 'trigger': 'input',
                                    'impact': 'fails', 'evidence': 'failure'}]
        report = self.data / 'result.json'
        report.write_text(json.dumps(self.result), encoding='utf-8')
        before = {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()}
        ctx, remaining = cli.argparse.ArgumentParser(add_help=False).parse_known_args([])
        ctx.data_dir, ctx.repo, ctx.root = str(self.data), str(self.data), str(Path(__file__).resolve().parents[1])
        args = cli.parser().parse_args(['_run', 'validate-result', '--run', self.run['run_id'], '--input', str(report)])
        result = cli.dispatch(args, ctx)
        self.assertEqual(result['scope'], 'schema_and_assignment')
        self.assertFalse(result['state_changed'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()})

    def test_invalid_criterion_actionable_and_not_coerced(self):
        self.result['criteria_results'] = [{'criterion': 'works', 'status': 'verified',
                                           'revision': 'abc', 'evidence': 'something'}]
        before = copy.deepcopy(self.result)
        with self.assertRaisesRegex(storage.DevFlowError, r'criteria_results\[0\].*passed, failed, not_run'):
            state.validate_result(self.task, self.result)
        self.assertEqual(self.result, before)

    def test_spec_contains_complete_partial_contract(self):
        spec = orca.spec(self.run, self.task, Path(__file__).resolve().parents[1])['spec']
        self.assertIn('_run validate-result', spec)
        self.assertIn('criteria_results[].status=passed|failed|not_run', spec)
        self.assertIn('"status": "partial"', spec)
        self.assertIn('Retain every blocker', spec)

    def test_utf8_even_under_legacy_environment(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/devflow.py'
        proc = subprocess.run([sys.executable, str(script), 'feature', 'á→文'],
                              env={**os.environ, 'PYTHONIOENCODING': 'cp1252'}, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('á→文', proc.stdout.decode('utf-8'))

    def test_applied_cleanup_error_exit_preserves_details(self):
        with patch.object(cli, 'dispatch', return_value={'applied': True, 'errors': ['still present']}), \
                patch.object(cli.sys, 'stdout', new=__import__('io').StringIO()) as output:
            self.assertEqual(cli.main(['cleanup', '--apply']), 2)
            self.assertEqual(json.loads(output.getvalue())['errors'], ['still present'])


if __name__ == '__main__':
    unittest.main()
