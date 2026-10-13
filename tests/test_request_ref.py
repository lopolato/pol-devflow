import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGED = 'Literal request changed after start'


class RequestRefTests(unittest.TestCase):
    """The user's literal request is stored by reference at start and guarded by its hash."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.data = self.root / 'data'
        self.repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(*args)
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def request_file(self, content, name='request.txt'):
        path = self.root / name
        path.write_bytes(content)
        return str(path)

    def start_run(self, *extra):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'Phone field', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co', *extra)

    def start_lite(self, *extra, ok=True):
        return self.cli('_lite', 'start', '--mode', 'error', '--request', 'Login 500', '--owner', 'co', *extra, ok=ok)

    def assert_ref(self, ref, expected_path, content, source):
        self.assertEqual(set(ref), {'path', 'sha256', 'source', 'bytes'})
        self.assertEqual(Path(ref['path']), expected_path.resolve())
        self.assertTrue(Path(ref['path']).is_absolute())
        self.assertEqual(Path(ref['path']).read_bytes(), content)
        self.assertEqual(ref['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual((ref['source'], ref['bytes']), (source, len(content)))

    # Start ------------------------------------------------------------------------------

    def test_run_start_stores_literal_request_from_file_or_inline(self):
        literal = 'Quiero que el teléfono sea obligatorio\nsolo en el alta, no en la edición.\n'.encode('utf-8')
        run = self.start_run('--request-file', self.request_file(literal))
        self.assert_ref(run['request_ref'], self.data / 'runs' / run['run_id'] / 'request.md', literal, 'file')
        saved = json.loads((self.data / 'runs' / run['run_id'] / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['request_ref'], run['request_ref'])
        self.assertEqual(saved['request'], 'Phone field')
        self.git('switch', 'main')
        inline = self.start_run()
        self.assert_ref(inline['request_ref'], self.data / 'runs' / inline['run_id'] / 'request.md',
                        b'Phone field', 'inline')

    def test_lite_start_stores_literal_request_from_file_or_inline(self):
        literal = 'El login devuelve 500 si el email lleva mayúsculas.\n'.encode('utf-8')
        record = self.start_lite('--request-file', self.request_file(literal))
        self.assert_ref(record['request_ref'], self.data / 'lite' / (record['id'] + '.request.md'), literal, 'file')
        saved = json.loads((self.data / 'lite' / (record['id'] + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(saved['request_ref'], record['request_ref'])
        self.git('switch', 'main')
        inline = self.start_lite()
        self.assert_ref(inline['request_ref'], self.data / 'lite' / (inline['id'] + '.request.md'),
                        b'Login 500', 'inline')

    def test_request_file_limits_refuse_before_any_branch_or_state(self):
        cases = {'empty': b'', 'blank': b' \n\t\n', 'too-large': b'x' * (64 * 1024 + 1),
                 'not-utf8': 'café'.encode('latin-1')}
        for name, content in cases.items():
            path = self.request_file(content, name + '.txt')
            for start in (self.start_lite, lambda *a, ok=True: self.cli(
                    '_run', 'start', '--mode', 'feature', '--request', 'Phone', '--criterion', 'c1',
                    '--runtime', 'claude', '--owner', 'co', *a, ok=ok)):
                with self.subTest(case=name):
                    error = start('--request-file', path, ok=False)
                    self.assertIn('request', error.lower())
                    self.assertEqual(self.git('branch', '--show-current'), 'main')
                    self.assertEqual(self.git('branch', '--format=%(refname:short)'), 'main')
                    self.assertFalse((self.data / 'runs').exists() and any((self.data / 'runs').iterdir()))
                    self.assertFalse((self.data / 'lite').exists() and any((self.data / 'lite').iterdir()))
        self.assertIn('--request-file', self.start_lite('--request-file', str(self.root / 'missing.txt'), ok=False))
        exact = self.request_file(b'y' * (64 * 1024), 'exact.txt')
        self.assertEqual(self.start_lite('--request-file', exact)['request_ref']['bytes'], 64 * 1024)

    def test_request_file_only_applies_to_start(self):
        run = self.start_run()
        path = self.request_file(b'literal')
        self.assertIn('--request-file', self.cli('_run', 'show', '--run', run['run_id'], '--request-file', path,
                                                 ok=False))
        self.git('switch', 'main')
        record = self.start_lite()
        self.assertIn('--request-file', self.cli('_lite', 'status', '--lite', record['id'], '--request-file', path,
                                                 ok=False))

    # Packets ----------------------------------------------------------------------------

    def test_task_packet_and_template_include_request_ref(self):
        run = self.start_run('--request-file', self.request_file(b'Literal: phone required on signup\n'))
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                        '--objective', 'Add the phone validation')
        self.assertEqual(task['request_ref'], run['request_ref'])
        self.assertEqual(task['objective'], 'Add the phone validation')
        template = self.cli('_run', 'template', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'])
        self.assertEqual(template['request_ref'], run['request_ref'])

    # Hash gates -------------------------------------------------------------------------

    def test_run_record_refuses_after_literal_request_changed(self):
        run = self.start_run('--request-file', self.request_file(b'Original literal request\n'))
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                        '--objective', 'small task')
        result = {'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'worker-1',
                  'role': 'implementer', 'status': 'done', 'summary': 'No product changes',
                  'observed_revision': run['base_revision'], 'result_revision': None}
        stored = Path(run['request_ref']['path'])
        stored.write_bytes(b'Paraphrased request\n')
        for extra in (('--dry-run',), ()):
            error = self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                             '--brief', '--input', self.write('result.json', result), *extra, ok=False)
            self.assertIn(CHANGED, error)
        stored.unlink()
        self.assertIn(CHANGED, self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id',
                                        task['task_id'], '--brief', '--input', self.write('r.json', result), ok=False))
        stored.write_bytes(b'Original literal request\n')
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                 '--brief', '--input', self.write('ok.json', result))

    def test_lite_review_refuses_after_literal_request_changed(self):
        record = self.start_lite('--review')
        (self.repo / 'app.py').write_text('fixed\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix login')
        self.cli('_lite', 'review-diff', '--lite', record['id'], '--owner', 'co', '--author-id', 'lite-1')
        review = self.write('review.json', {'worker_id': 'rev-1', 'verdict': 'passed',
                                            'revision': self.git('rev-parse', 'HEAD')})
        stored = Path(record['request_ref']['path'])
        stored.write_bytes(b'Login 500 (rewritten)')
        self.assertIn(CHANGED, self.cli('_lite', 'review', '--lite', record['id'], '--owner', 'co',
                                        '--input', review, ok=False))
        self.assertIsNone(json.loads((self.data / 'lite' / (record['id'] + '.json')).read_text(
            encoding='utf-8')).get('review'))
        stored.write_bytes(b'Login 500')
        result = self.cli('_lite', 'review', '--lite', record['id'], '--owner', 'co', '--input', review)
        self.assertEqual(result['review']['verdict'], 'passed')

    # Cleanup ----------------------------------------------------------------------------

    def test_purge_history_removes_lite_request_file(self):
        record = self.start_lite()
        (self.repo / 'app.py').write_text('fixed\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix login')
        self.git('switch', 'main')
        self.git('merge', '--no-ff', '-m', 'merge', record['branch'])
        self.cli('cleanup', '--apply')
        request = self.data / 'lite' / (record['id'] + '.request.md')
        self.assertTrue(request.exists())
        self.cli('cleanup', '--apply', '--purge-history')
        self.assertFalse((self.data / 'lite' / (record['id'] + '.json')).exists())
        self.assertFalse(request.exists())


if __name__ == '__main__':
    unittest.main()
