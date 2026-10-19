"""Compact responses keep guards, evidence and durable handoffs intact."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompactOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.data = self.root / 'repo', self.root / 'data'
        self.repo.mkdir()
        for command in (('init', '-b', 'main'), ('config', 'user.name', 'Test'),
                        ('config', 'user.email', 'test@example.invalid')):
            subprocess.run(['git', *command], cwd=self.repo, check=True, capture_output=True)
        (self.repo / 'app.txt').write_text('initial', encoding='utf-8')
        subprocess.run(['git', 'add', 'app.txt'], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'initial'], cwd=self.repo, check=True, capture_output=True)

    def raw(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--repo', str(self.repo),
                               '--data-dir', str(self.data), *args], capture_output=True, text=True, encoding='utf-8')

    def cli(self, *args):
        result = self.raw(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def start(self, *args):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'Short title',
                        '--criterion', 'c1', '--runtime', 'codex', '--owner', 'co', *args)

    def test_compact_start_preserves_literal_request_and_bootstrap_context(self):
        literal = 'Petición completa de prueba.\nConservar también esta segunda línea.'
        request = self.root / 'request.md'
        request.write_text(literal, encoding='utf-8')
        run = self.start('--compact', '--request-file', str(request))
        self.assertEqual(Path(run['request_ref']['path']).read_text(encoding='utf-8'), literal)
        self.assertEqual(len(run['current_revision']), 40)
        self.assertIn('identity', run)
        self.assertIn('context', run)
        saved = json.loads(Path(run['state_path']).read_text(encoding='utf-8'))
        self.assertEqual(saved['current_revision'], run['current_revision'])
        self.assertEqual(saved['request_ref'], run['request_ref'])
        self.assertNotIn('tasks', run)
        self.assertEqual(run['budget']['tokens_status'], 'unavailable')

    def test_record_reduces_output_without_discarding_results_or_warnings(self):
        run = self.start()
        call = ('--run', run['run_id'], '--owner', 'co')
        detail = 'diagnostic evidence ' * 400
        for index in range(2):
            task = self.cli('_run', 'task', *call, '--role', 'explorer', '--objective', 'Read')
            result = self.cli('_run', 'template', *call, '--task-id', task['task_id'])
            result.pop('request_ref', None)
            result.update(status='done', summary=detail, worker_id='same-reader',
                          result_revision=run['current_revision'])
            response = self.raw('_run', 'record', *call, '--compact', '--input', self.write(f'r{index}.json', result))
            self.assertEqual(response.returncode, 0, response.stderr)
        compact = json.loads(response.stdout)
        saved_text = (self.data / 'runs' / run['run_id'] / 'state.json').read_text(encoding='utf-8')
        saved = json.loads(saved_text)
        self.assertEqual(saved['tasks'][0]['result']['summary'], detail)
        self.assertEqual(len(saved['tasks']), 2)
        self.assertLess(len(response.stdout), len(saved_text) // 2)
        self.assertNotIn(detail, response.stdout)
        self.assertIn('warnings', compact)
        self.assertEqual(compact['budget']['assignments_used'], 2)
        self.assertEqual(compact['budget']['workers_used'], 2)  # Compatibility alias.
        self.assertEqual(compact['budget']['worker_identities_known'], 1)
        self.assertEqual(compact['budget']['tokens_status'], 'unavailable')
        self.cli('_metrics', 'add', *call, '--role', 'explorer', '--tokens', '0')
        budget = self.cli('status', '--brief', '--run', run['run_id'])['budget']
        self.assertEqual(budget['tokens_known'], 0)
        self.assertEqual(budget['tokens_status'], 'reported')
        review_task = self.cli('_run', 'task', *call, '--role', 'reviewer', '--objective', 'Independent review')
        review = self.cli('_run', 'template', *call, '--task-id', review_task['task_id'])
        review.pop('request_ref', None)
        review.update(status='done', summary='Reviewed the full diff', worker_id='independent-reviewer',
                      result_revision=run['current_revision'], review={'verdict': 'passed', 'coverage': 'Full diff'})
        accepted = self.cli('_run', 'record', *call, '--compact', '--input', self.write('review.json', review))
        self.assertEqual(accepted['review']['verdict'], 'passed')
        self.assertEqual(accepted['review']['worker_id'], 'independent-reviewer')

    def test_compact_does_not_bypass_owner_or_mutate_unsupported_actions(self):
        run = self.start()
        state_file = self.data / 'runs' / run['run_id'] / 'state.json'
        before = state_file.read_bytes()
        payload = self.write('update.json', {'phase': 'unexpected'})
        wrong_owner = self.raw('_run', 'update', '--run', run['run_id'], '--owner', 'other',
                               '--input', payload, '--compact')
        self.assertNotEqual(wrong_owner.returncode, 0)
        self.assertIn('Coordinator identity mismatch', wrong_owner.stderr)
        unsupported = self.raw('_run', 'task', '--run', run['run_id'], '--owner', 'co',
                               '--role', 'explorer', '--objective', 'Read', '--compact')
        self.assertNotEqual(unsupported.returncode, 0)
        self.assertIn('full handoff', unsupported.stderr)
        self.assertEqual(state_file.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
