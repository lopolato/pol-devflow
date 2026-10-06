import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import adapters, config


class LiteCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.data = self.root / 'data'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / '.gitignore').write_text('node_modules/\n.env\n')
        (self.repo / 'app.py').write_text('original\n')
        (self.repo / 'docs').mkdir()
        (self.repo / 'docs/PROJECT.md').write_text('Verified project context\n')
        self.git('add', '.gitignore', 'app.py', 'docs/PROJECT.md')
        self.git('commit', '-m', 'initial')

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout) if result.stdout.strip().startswith('{') else result.stdout
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def lite(self, request='Login devuelve 500', mode='error'):
        return self.cli('_lite', 'start', '--mode', mode, '--request', request)

    def lite_commit(self, record, text='fixed\n'):
        (self.repo / 'app.py').write_text(text)
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix login')

    def items(self, result):
        return {item['branch']: item for item in result['items']}

    def test_lite_branch_in_current_checkout_keeps_ignored_files(self):
        (self.repo / 'node_modules').mkdir()
        (self.repo / 'node_modules/lib.js').write_text('dependency\n')
        (self.repo / '.env').write_text('SECRET=1\n')
        record = self.lite()
        self.assertTrue(record['branch'].startswith('fix/login-devuelve-500-'))
        self.assertEqual(self.git('branch', '--show-current'), record['branch'])
        self.assertEqual(record['previous_branch'], 'main')
        self.assertEqual(Path(record['workspace']).resolve(), self.repo.resolve())
        # No worktree: local dependencies and configuration stay available.
        self.assertTrue((self.repo / 'node_modules/lib.js').exists())
        self.assertTrue((self.repo / '.env').exists())
        self.assertEqual(len(self.git('worktree', 'list').splitlines()), 1)
        self.assertTrue((self.data / 'lite' / (record['id'] + '.json')).exists())
        self.lite_commit(record)
        self.assertEqual(self.git('show', 'main:app.py'), 'original')

    def test_lite_refuses_dirty_checkout_and_optimize(self):
        (self.repo / 'app.py').write_text('user change\n')
        error = self.cli('_lite', 'start', '--mode', 'feature', '--request', 'x', ok=False)
        self.assertIn('clean checkout', error)
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertEqual((self.repo / 'app.py').read_text(), 'user change\n')
        self.assertFalse((self.data / 'lite').exists())
        self.cli('_lite', 'start', '--mode', 'optimize', '--request', 'x', ok=False)
        self.cli('optimize', '--lite', 'x', ok=False)

    def test_level_flags_route_to_lite_workflow(self):
        result = self.cli('feature', '--lite', '--plan-only', 'Add phone')
        self.assertEqual(result['level'], 'lite')
        self.assertTrue(result['workflow'].endswith('lite.md'))
        self.assertEqual(self.cli('error', 'Bug')['level'], 'auto')
        self.assertEqual(self.cli('error', '--full', 'Bug')['level'], 'full')
        self.assertEqual(self.cli('optimize', 'Faster')['level'], 'full')
        self.cli('feature', '--lite', '--full', 'x', ok=False)
        self.assertFalse(self.data.exists())

    def test_lite_profile_uses_own_contract_and_model(self):
        value = config.defaults()
        value['profiles']['lite'] = {'codex': {'model': 'small-codex', 'effort': 'medium'},
                                     'claude': {'model': 'small-claude'}}
        claude = adapters.render_all('claude', value, ROOT)['pol-lite.md']
        self.assertIn('model: "small-claude"', claude)
        self.assertIn('# Lite', claude)
        self.assertNotIn('Contrato del worker', claude)
        codex = adapters.render_all('codex', value, ROOT)['pol-lite.toml']
        self.assertIn('model = "small-codex"', codex)
        self.assertNotIn('read-only', codex)
        self.assertNotIn('lite', config.TASK_ROLES)

    def test_lite_role_is_not_a_full_mode_assignment(self):
        self.cli('_run', 'task', '--run', 'x', '--owner', 'co', '--role', 'lite', '--objective', 'x', ok=False)

    def test_cleanup_lists_read_only_and_removes_only_after_merge(self):
        record = self.lite()
        self.lite_commit(record)
        self.git('switch', 'main')
        before = sorted(p.as_posix() for p in self.data.rglob('*'))
        listed = self.items(self.cli('cleanup'))[record['branch']]
        self.assertEqual(listed['action'], 'keep')
        self.assertFalse(listed['merged'])
        self.assertEqual(sorted(p.as_posix() for p in self.data.rglob('*')), before)
        applied = self.cli('cleanup', '--apply')
        self.assertEqual(applied['removed'], [])
        self.assertIn(record['branch'], self.git('branch', '--list', record['branch']))
        self.git('merge', '--no-ff', '-m', 'merge', record['branch'])
        self.assertEqual(self.items(self.cli('cleanup'))[record['branch']]['action'], 'remove')
        applied = self.cli('cleanup', '--apply')
        self.assertEqual([r['branch'] for r in applied['removed']], [record['branch']])
        self.assertEqual(self.git('branch', '--list', record['branch']), '')
        self.assertTrue((self.data / 'lite' / (record['id'] + '.json')).exists())
        self.assertEqual((self.repo / 'app.py').read_text(), 'fixed\n')
        history = self.cli('cleanup')
        self.assertNotIn(record['branch'], self.items(history))
        self.assertEqual(history['history_retained']['branches'], [record['branch']])
        self.cli('cleanup', '--apply', '--purge-history')
        self.assertFalse((self.data / 'lite' / (record['id'] + '.json')).exists())
        self.assertEqual(self.cli('cleanup')['items'], [])

    def test_cleanup_keeps_checked_out_branch_and_discard_needs_confirmation(self):
        record = self.lite()
        self.lite_commit(record)
        reasons = ' '.join(self.items(self.cli('cleanup'))[record['branch']]['reasons'])
        self.assertIn('checked out', reasons)
        self.assertIn('not merged', reasons)
        self.git('switch', 'main')
        self.assertIn('--apply', self.cli('cleanup', '--discard', record['branch'], ok=False))
        self.assertIn('DevFlow-recorded', self.cli('cleanup', '--apply', '--discard', 'main', ok=False))
        applied = self.cli('cleanup', '--apply', '--discard', record['branch'])
        self.assertTrue(applied['removed'][0]['discarded_unmerged'])
        self.assertEqual(self.git('branch', '--list', record['branch']), '')

    def test_cleanup_ignores_branches_devflow_did_not_create(self):
        self.git('switch', '-c', 'feature/manual')
        self.git('switch', 'main')
        self.lite()
        self.git('switch', 'main')
        branches = self.items(self.cli('cleanup'))
        self.assertNotIn('feature/manual', branches)
        self.assertNotIn('main', branches)
        self.cli('cleanup', '--apply')
        self.assertIn('feature/manual', self.git('branch', '--list', 'feature/manual'))

    def test_cleanup_full_worktree_waits_for_closed_run_and_clean_tree(self):
        run = self.cli('_run', 'start', '--mode', 'feature', '--request', 'Phone', '--criterion', 'c1',
                       '--runtime', 'claude', '--owner', 'co')
        workspace, branch = Path(run['workspace']), run['branch']
        (workspace / 'app.py').write_text('feature\n')
        self.cli('_git', 'commit', '--workspace', str(workspace), '--expected-branch', branch,
                 '--path', 'app.py', '--message', 'Phone')
        self.cli('_run', 'refresh', '--run', run['run_id'], '--owner', 'co')
        self.git('merge', '--no-ff', '-m', 'merge', branch)
        item = self.items(self.cli('cleanup'))[branch]
        self.assertEqual(item['action'], 'keep')
        self.assertIn('run still active', ' '.join(item['reasons']))
        self.assertEqual(self.cli('cleanup', '--apply', '--purge-history')['removed'], [])
        self.assertTrue((self.data / 'runs' / run['run_id'] / 'state.json').exists())
        self.cli('_run', 'close', '--run', run['run_id'], '--owner', 'co', '--status', 'partial')
        (workspace / 'scratch.txt').write_text('untracked\n')
        self.assertIn('uncommitted', ' '.join(self.items(self.cli('cleanup'))[branch]['reasons']))
        (workspace / 'scratch.txt').unlink()
        applied = self.cli('cleanup', '--apply')
        self.assertEqual(applied['errors'], [])
        self.assertFalse(workspace.exists())
        self.assertEqual(self.git('branch', '--list', branch), '')
        self.assertTrue((self.data / 'runs' / run['run_id'] / 'state.json').exists())
        self.assertTrue((self.data / 'runs' / run['run_id'] / 'context.md').exists())
        before = (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()
        self.cli('cleanup', '--purge-history')
        self.assertEqual((self.data / 'runs' / run['run_id'] / 'state.json').read_bytes(), before)
        self.cli('cleanup', '--apply', '--purge-history')
        self.assertFalse((self.data / 'runs' / run['run_id']).exists())
        self.assertEqual((self.repo / 'docs/PROJECT.md').read_text(), 'Verified project context\n')


if __name__ == '__main__':
    unittest.main()
