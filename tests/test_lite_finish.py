import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import gitops


class LiteFinishTests(unittest.TestCase):
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

    def start(self, *extra):
        return self.cli('_lite', 'start', '--mode', 'error', '--request', 'Login devuelve 500', *extra)

    def commit(self, record):
        (self.repo / 'app.py').write_text('fixed\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix login')
        return self.git('rev-parse', 'HEAD')

    def record(self, lite_id):
        return json.loads((self.data / 'lite' / (lite_id + '.json')).read_text(encoding='utf-8'))

    def test_finish_completes_and_stats_count_elapsed_time(self):
        record = self.start()
        head = self.commit(record)
        result = self.cli('_lite', 'finish', '--lite', record['id'])
        self.assertEqual((result['status'], result['final_revision'], result['commits']), ('completed', head, 1))
        saved = self.record(record['id'])
        self.assertEqual(saved['status'], 'completed')
        self.assertTrue(saved['closed_at'])
        stats = self.cli('stats')
        self.assertEqual(stats['tasks']['lite:error']['status'], {'completed': 1})
        self.assertEqual(stats['tasks']['lite:error']['wall_clock_known'], 1)
        self.assertIn('already closed', self.cli('_lite', 'finish', '--lite', record['id'], ok=False))

    def test_finish_refuses_without_commits_and_partial_needs_reason(self):
        record = self.start()
        self.assertIn('no commits', self.cli('_lite', 'finish', '--lite', record['id'], ok=False))
        self.assertIn('--reason', self.cli('_lite', 'finish', '--lite', record['id'], '--status', 'cancelled', ok=False))
        result = self.cli('_lite', 'finish', '--lite', record['id'], '--status', 'cancelled',
                          '--reason', 'User dropped the task')
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.record(record['id'])['close_reason'], 'User dropped the task')

    def test_merged_and_deleted_branch_completes_with_explicit_revision(self):
        record = self.start()
        head = self.commit(record)
        self.git('switch', 'main')
        self.git('merge', '--ff-only', record['branch'])
        self.git('branch', '-d', record['branch'])
        self.assertIn('--revision', self.cli('_lite', 'finish', '--lite', record['id'], ok=False))
        other = self.git('rev-list', '--max-parents=0', 'HEAD')
        self.assertIn('descends', self.cli('_lite', 'finish', '--lite', record['id'], '--revision',
                                           'does-not-exist', ok=False))
        self.assertIn('no commits', self.cli('_lite', 'finish', '--lite', record['id'], '--revision', other, ok=False))
        result = self.cli('_lite', 'finish', '--lite', record['id'], '--revision', 'main')
        self.assertEqual((result['status'], result['final_revision']), ('completed', head))

    def test_lite_review_must_be_current_to_complete(self):
        record = self.start('--review')
        self.commit(record)
        self.assertIn('current passed review', self.cli('_lite', 'finish', '--lite', record['id'], ok=False))

    def test_finish_flags_rejected_on_other_actions(self):
        record = self.start()
        self.assertIn('only apply to _lite finish', self.cli('_lite', 'status', '--lite', record['id'],
                                                             '--reason', 'x', ok=False))

    def test_large_untracked_set_is_sampled_with_count(self):
        (self.repo / 'assets').mkdir()
        for index in range(25):
            (self.repo / 'assets' / f'img{index:02}.png').write_text('x')
        record = self.start()
        self.assertEqual(record['untracked_preserved_count'], 25)
        self.assertEqual(len(record['untracked_preserved']), gitops.UNTRACKED_LISTED)
        self.assertEqual(self.record(record['id'])['untracked_preserved_count'], 25)


class BranchSlugTests(unittest.TestCase):
    def test_accents_are_transliterated_and_cut_at_word_boundary(self):
        slug = gitops.branch_slug('Al pulsar Solicitar más información desde la página principal, el desplazamiento')
        self.assertEqual(slug, 'al-pulsar-solicitar-mas-informacion')
        self.assertLessEqual(len(slug), gitops.BRANCH_SLUG_MAX)

    def test_short_and_symbol_only_descriptions(self):
        self.assertEqual(gitops.branch_slug('Añadir IVA'), 'anadir-iva')
        self.assertEqual(gitops.branch_slug('¿¿??'), 'task')
        self.assertEqual(gitops.branch_slug('x' * 60), 'x' * gitops.BRANCH_SLUG_MAX)
        self.assertTrue(gitops.branch_name('error', 'Login 500').startswith('fix/login-500-'))


if __name__ == '__main__':
    unittest.main()
