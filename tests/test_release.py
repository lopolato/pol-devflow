import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/release.py'
_spec = importlib.util.spec_from_file_location('devflow_release', SCRIPT)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class ReleaseTests(unittest.TestCase):
    """Temp repositories with a bare origin; never GitHub, never the real runtime homes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / 'origin.git'
        git(base, 'init', '--bare', '-b', 'main', str(self.origin))
        self.repo = base / 'work'
        self.repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'Test'),
                     ('config', 'user.email', 'test@example.invalid'), ('config', 'commit.gpgsign', 'false'),
                     ('config', 'tag.gpgsign', 'false'), ('remote', 'add', 'origin', str(self.origin))):
            git(self.repo, *args)
        self.write_release('1.0.16')
        git(self.repo, 'tag', '-a', 'v1.0.16', '-m', 'Pol DevFlow 1.0.16')
        self.write_release('1.0.17')
        git(self.repo, 'push', 'origin', 'main', 'v1.0.16')

    def write_release(self, version, verification=None, readme=None):
        init = self.repo / 'scripts/devflow/__init__.py'
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text(f'"""Package."""\n__version__ = \'{version}\'\n', encoding='utf-8')
        (self.repo / 'VERIFICATION.md').write_text(
            verification if verification is not None else f'# Historial\n\n## {version} · Cambios · 09/10/2026\n\nok\n',
            encoding='utf-8')
        (self.repo / 'README.md').write_text(
            readme if readme is not None else f'# Pol DevFlow {version}\n\nTexto.\n', encoding='utf-8')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-m', f'Pol DevFlow {version}')

    def release(self, *args, stdin=subprocess.DEVNULL):
        return subprocess.run([sys.executable, str(SCRIPT), *args, '--repo', str(self.repo)], stdin=stdin,
                              capture_output=True, text=True, encoding='utf-8', errors='replace')

    def in_process(self, *args, ci_runner):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release.main([*args, '--repo', str(self.repo)], ci_runner=ci_runner)
        return code, out.getvalue(), err.getvalue()

    def refs(self, repo):
        return git(repo, 'for-each-ref', '--format=%(refname) %(objectname)')

    def assert_refused(self, result, text):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, result.stderr)
        self.assertNotIn('v1.0.17', git(self.repo, 'tag', '--list'))

    # -- refusals ------------------------------------------------------
    def test_refuses_outside_main(self):
        git(self.repo, 'checkout', '-b', 'feat/x')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'current branch is feat/x')

    def test_refuses_dirty_tree_including_untracked(self):
        (self.repo / 'nuevo.txt').write_text('x', encoding='utf-8')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'not clean')

    def test_refuses_when_behind_origin(self):
        other = Path(self.tmp.name) / 'other'
        git(Path(self.tmp.name), 'clone', str(self.origin), str(other))
        git(other, 'config', 'user.name', 'Other')
        git(other, 'config', 'user.email', 'other@example.invalid')
        (other / 'extra.txt').write_text('x', encoding='utf-8')
        git(other, 'add', 'extra.txt')
        git(other, 'commit', '-m', 'extra')
        git(other, 'push', 'origin', 'main')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'behind or has diverged')

    def test_refuses_missing_verification_section(self):
        self.write_release('1.0.17', verification='# Historial\n\n## 1.0.16\n\n## 1.0.170\n')
        git(self.repo, 'push', 'origin', 'main')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'VERIFICATION.md needs a "## 1.0.17"')

    def test_refuses_readme_heading_mismatch(self):
        self.write_release('1.0.17', readme='# Pol DevFlow 1.0.16\n\n# Pol DevFlow 1.0.17\n')
        git(self.repo, 'push', 'origin', 'main')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'README.md first heading')

    def test_refuses_when_init_does_not_declare_version(self):
        result = self.release('1.0.18', '--skip-tests')
        self.assert_refused(result, 'declares 1.0.17, not 1.0.18')
        self.assertIn('feature branch', result.stderr)
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')

    def test_refuses_version_not_greater(self):
        git(self.repo, 'tag', '-a', 'v1.0.20', '-m', 'later', 'HEAD~1')
        self.assert_refused(self.release('1.0.17', '--skip-tests'), 'not greater than the current v1.0.20')
        self.assert_refused(self.release('1.0.x', '--skip-tests'), 'Invalid version')

    def test_refuses_existing_tag_local_or_remote(self):
        git(self.repo, 'tag', '-a', 'v1.0.17', '-m', 'x')
        result = self.release('1.0.17', '--skip-tests')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Tag v1.0.17 already exists', result.stderr)
        git(self.repo, 'push', 'origin', 'v1.0.17')
        git(self.repo, 'tag', '-d', 'v1.0.17')
        result = self.release('1.0.17', '--skip-tests', '--dry-run')  # no fetch: only ls-remote sees it
        self.assertEqual(result.returncode, 1)
        self.assertIn('already exists in origin', result.stderr)

    def test_evals_need_yes_when_not_interactive(self):
        self.assert_refused(self.release('1.0.17', '--skip-tests', '--evals'), '--evals needs --yes')

    # -- dry run and happy paths --------------------------------------
    def test_dry_run_changes_nothing(self):
        before = (self.refs(self.repo), self.refs(self.origin), git(self.repo, 'status', '--porcelain'))
        result = self.release('1.0.17', '--dry-run', '--push', '--install', '--evals')
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('unittest discover -s tests', 'scripts/validate.py', 'check_claude_nesting.py',
                         'git tag -a v1.0.17', 'git push --atomic origin refs/heads/main refs/tags/v1.0.17',
                         'scripts/install.py --runtime all', 'validate.py --runtime claude',
                         'validate.py --runtime codex', 'nothing was changed'):
            self.assertIn(expected, result.stdout)
        self.assertEqual(before, (self.refs(self.repo), self.refs(self.origin), git(self.repo, 'status', '--porcelain')))

    def test_happy_path_tags_main_without_committing(self):
        head = git(self.repo, 'rev-parse', 'HEAD')
        result = self.release('1.0.17', '--skip-tests')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--skip-tests', result.stdout)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)
        self.assertEqual(git(self.repo, 'rev-parse', 'v1.0.17^{commit}'), head)
        self.assertEqual(git(self.repo, 'cat-file', '-t', 'v1.0.17'), 'tag')
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.assertEqual(git(self.origin, 'tag', '--list', 'v1.0.17'), '')

    def test_push_publishes_main_and_tag(self):
        (self.repo / 'notes.txt').write_text('local ahead\n', encoding='utf-8')
        git(self.repo, 'add', 'notes.txt')
        git(self.repo, 'commit', '-m', 'ahead of origin')
        head = git(self.repo, 'rev-parse', 'HEAD')
        result = self.release('1.0.17', '--skip-tests', '--push')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.origin, 'rev-parse', 'main'), head)
        self.assertEqual(git(self.origin, 'rev-parse', 'v1.0.17^{commit}'), head)

    def test_runs_tests_and_validation_before_tagging(self):
        (self.repo / 'tests').mkdir()
        (self.repo / 'scripts/validate.py').write_text('print("healthy")\n', encoding='utf-8')
        test = self.repo / 'tests/test_ok.py'
        test.write_text('import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n',
                        encoding='utf-8')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-m', 'tests')
        git(self.repo, 'push', 'origin', 'main')
        result = self.release('1.0.17')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('v1.0.17', git(self.repo, 'tag', '--list'))
        git(self.repo, 'tag', '-d', 'v1.0.17')
        test.write_text(test.read_text(encoding='utf-8').replace('pass', 'self.fail("boom")'), encoding='utf-8')
        git(self.repo, 'commit', '-am', 'failing')
        git(self.repo, 'push', 'origin', 'main')
        self.assert_refused(self.release('1.0.17'), 'Unit tests failed')

    # -- GitHub CI check (injected runner; GitHub is never called) ------
    def use_github_origin(self):
        url = 'https://github.com/acme/pol-devflow.git'
        git(self.repo, 'config', f'url.{self.origin.as_posix()}.insteadOf', url)
        git(self.repo, 'remote', 'set-url', 'origin', url)

    def test_ci_check_refuses_unless_green(self):
        self.use_github_origin()
        calls = []

        def failing(slug, sha):
            calls.append((slug, sha))
            return 'failure', 'windows-latest / Python 3.12=failure'
        code, _, err = self.in_process('1.0.17', '--skip-tests', ci_runner=failing)
        self.assertEqual(code, 1)
        self.assertIn('windows-latest / Python 3.12=failure', err)
        self.assertEqual(calls, [('acme/pol-devflow', git(self.repo, 'rev-parse', 'HEAD'))])
        self.assertNotIn('v1.0.17', git(self.repo, 'tag', '--list'))
        code, out, _ = self.in_process('1.0.17', '--skip-tests', '--skip-ci-check', ci_runner=failing)
        self.assertEqual((code, len(calls)), (0, 1))
        self.assertIn('--skip-ci-check', out)

    def test_ci_check_success_and_unavailable_gh(self):
        self.use_github_origin()
        code, out, _ = self.in_process('1.0.17', '--skip-tests', '--dry-run', ci_runner=lambda s, h: None)
        self.assertEqual(code, 0)
        self.assertIn('gh is not available', out)
        code, out, _ = self.in_process('1.0.17', '--skip-tests', ci_runner=lambda s, h: ('success', '4 passed'))
        self.assertEqual(code, 0, out)
        self.assertIn('v1.0.17', git(self.repo, 'tag', '--list'))

    def test_local_origin_skips_ci_check(self):
        def never(slug, sha):
            raise AssertionError('GitHub must not be queried for a local origin')
        code, out, _ = self.in_process('1.0.17', '--skip-tests', '--dry-run', ci_runner=never)
        self.assertEqual(code, 0)
        self.assertIn('not a GitHub repository', out)


class ReleaseHelpersTests(unittest.TestCase):
    def test_github_slug(self):
        for url in ('https://github.com/acme/pol-devflow.git', 'git@github.com:acme/pol-devflow.git',
                    'ssh://git@github.com/acme/pol-devflow', 'https://token@github.com/acme/pol-devflow/'):
            self.assertEqual(release.github_slug(url), 'acme/pol-devflow', url)
        for url in ('C:/tmp/origin.git', '/srv/origin.git', 'https://gitlab.com/acme/x.git'):
            self.assertIsNone(release.github_slug(url))

    def test_summarize_check_runs(self):
        run = lambda name, status='completed', conclusion='success': {
            'name': name, 'status': status, 'conclusion': conclusion}
        self.assertEqual(release.summarize_check_runs({'check_runs': []})[0], 'missing')
        self.assertEqual(release.summarize_check_runs({'check_runs': [run('a'), run('b', conclusion='skipped')]})[0],
                         'success')
        self.assertEqual(release.summarize_check_runs({'check_runs': [run('a'), run('b', 'in_progress', None)]})[0],
                         'pending')
        state, detail = release.summarize_check_runs({'check_runs': [run('a', conclusion='failure'),
                                                                     run('b', 'queued', None)]})
        self.assertEqual((state, detail), ('failure', 'a=failure'))

    def test_parse_version_is_numeric(self):
        self.assertGreater(release.parse_version('1.0.17'), release.parse_version('1.0.9'))
        self.assertEqual(release.parse_version('1.1.0'), release.parse_version('1.1'))


if __name__ == '__main__':
    unittest.main()
