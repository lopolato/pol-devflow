import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'evals' / 'run_evals.py'

ev = None
if RUNNER.exists():  # the installer copies tests/ but not evals/
    _spec = importlib.util.spec_from_file_location('run_evals', RUNNER)
    ev = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ev)

FIXED_CALC = 'IVA = 0.21\n\n\ndef total(prices):\n    return round(sum(prices) * (1 + IVA), 2)\n'


def scenario(sid):
    return next(s for s in ev.load_scenarios() if s['id'] == sid)


def git(repo, *args):
    return ev.git(repo, *args)


def commit(repo, files, message='change'):
    for name, content in files.items():
        path = Path(repo) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)


@unittest.skipIf(ev is None, 'evals/ is not part of this copy')
class EvalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def build(self, sid='lite-small-bug', **override):
        fixture = dict(scenario(sid)['fixture'], **override)
        repo = self.root / 'repo'
        return repo, ev.build_fixture(fixture, repo)

    def check(self, repo, baseline, exp, transcript=''):
        return ev.check_expectation(repo, baseline, transcript, exp)

    # ---- scenarios

    def test_scenarios_load_and_validate(self):
        scenarios = ev.load_scenarios()
        self.assertGreaterEqual(len(scenarios), 5)
        for path in sorted((ROOT / 'evals' / 'scenarios').glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(path.stem, data['id'])
            self.assertEqual(ev.validate_scenario(data), [], path.name)
        used = {e['type'] for s in scenarios for e in s['expectations']}
        self.assertTrue(used <= set(ev.VOCABULARY))

    def test_validate_rejects_bad_expectations(self):
        base = scenario('plan-only')
        bad = dict(base, expectations=[{'type': 'nope'}, {'type': 'branch_created_prefix'},
                                       {'type': 'main_unchanged', 'extra': 1},
                                       {'type': 'command_passes', 'command': 'python -m unittest'}])
        errors = ev.validate_scenario(bad)
        self.assertEqual(len(errors), 4, errors)
        self.assertIn('missing key: prompt', ev.validate_scenario({'id': 'x'}))

    def test_unknown_scenario_filter_fails(self):
        with self.assertRaises(ValueError):
            ev.load_scenarios(only=['does-not-exist'])

    # ---- fixture builder

    def test_fixture_is_committed_clean_repo_on_main(self):
        repo, baseline = self.build()
        self.assertEqual(git(repo, 'symbolic-ref', '--short', 'HEAD').strip(), 'main')
        self.assertEqual(baseline['status'], '')
        self.assertEqual(list(baseline['branches']), ['main'])
        self.assertEqual(baseline['remotes'], [])
        self.assertIn('calc.py', git(repo, 'ls-tree', '-r', '--name-only', 'main'))

    def test_fixture_dirty_change_left_uncommitted(self):
        repo, baseline = self.build('lite-dirty-checkout')
        self.assertIn(' M README.md', baseline['status'])
        expected = scenario('lite-dirty-checkout')['fixture']['dirty']['README.md']
        self.assertEqual((repo / 'README.md').read_text(encoding='utf-8'), expected)
        self.assertNotIn('Nota local', git(repo, 'show', 'main:README.md'))

    def test_fixture_extra_branches(self):
        repo, baseline = self.build('cleanup-no-history')
        self.assertEqual(set(baseline['branches']), {'main', 'fix/manual-old', 'feature/wip'})
        self.assertEqual(baseline['branches']['main'], baseline['branches']['fix/manual-old'])
        self.assertNotEqual(baseline['branches']['main'], baseline['branches']['feature/wip'])
        self.assertEqual(baseline['status'], '')

    # ---- full-scenario simulations

    def test_simulated_good_lite_run_passes_all(self):
        repo, baseline = self.build()
        git(repo, 'checkout', '-q', '-b', 'fix/total-iva-1234abcd')
        commit(repo, {'calc.py': FIXED_CALC}, 'fix: IVA')
        results = ev.evaluate(repo, baseline, 'DEVFLOW LITE RESULT\nEstado: done',
                              scenario('lite-small-bug')['expectations'])
        self.assertTrue(all(r['passed'] for r in results), [r for r in results if not r['passed']])

    def test_simulated_bad_run_on_main_fails(self):
        repo, baseline = self.build()
        commit(repo, {'calc.py': FIXED_CALC, 'docs/devflow/reports/x.md': 'r\n'}, 'fix on main')
        results = {r['type']: r['passed'] for r in ev.evaluate(
            repo, baseline, 'full', scenario('lite-small-bug')['expectations'])}
        for kind in ('branch_created_prefix', 'main_unchanged', 'path_absent', 'command_passes',
                     'transcript_contains_any'):
            self.assertFalse(results[kind], kind)

    def test_simulated_memory_run_needs_report(self):
        repo, baseline = self.build('lite-memory-opt-in')
        exps = scenario('lite-memory-opt-in')['expectations']
        git(repo, 'checkout', '-q', '-b', 'fix/iva')
        commit(repo, {'calc.py': FIXED_CALC})
        by_type = {r['type']: r['passed'] for r in ev.evaluate(repo, baseline, '', exps)}
        self.assertFalse(by_type['path_present'])
        commit(repo, {'docs/devflow/reports/fix-iva.md': '# bugfix\n', 'docs/devflow/memory.json': '{}\n'})
        results = ev.evaluate(repo, baseline, '', exps)
        self.assertTrue(all(r['passed'] for r in results), [r for r in results if not r['passed']])

    # ---- individual expectation types

    def test_branch_expectations(self):
        repo, baseline = self.build('cleanup-no-history')
        for exp in ({'type': 'no_new_branches'}, {'type': 'branches_preserved'}, {'type': 'no_new_commits'},
                    {'type': 'main_unchanged'}):
            self.assertTrue(self.check(repo, baseline, exp)[0], exp)
        git(repo, 'branch', '-D', 'fix/manual-old')
        self.assertFalse(self.check(repo, baseline, {'type': 'branches_preserved'})[0])
        git(repo, 'branch', 'feature/other')
        self.assertFalse(self.check(repo, baseline, {'type': 'no_new_branches'})[0])
        self.assertTrue(self.check(repo, baseline, {'type': 'branch_created_prefix', 'prefix': 'feature/'})[0])
        self.assertFalse(self.check(repo, baseline, {'type': 'branch_created_prefix', 'prefix': 'fix/'})[0])
        self.assertTrue(self.check(repo, baseline, {'type': 'no_new_commits'})[0])
        git(repo, 'checkout', '-q', 'feature/wip')
        commit(repo, {'wip.py': 'VALUE = 2\n'})
        self.assertFalse(self.check(repo, baseline, {'type': 'no_new_commits'})[0])
        self.assertFalse(self.check(repo, baseline, {'type': 'branches_preserved'})[0])

    def test_max_product_files_excludes_devflow_docs(self):
        repo, baseline = self.build()
        exp = {'type': 'max_product_files_changed', 'max': 3, 'branch_prefix': 'fix/'}
        git(repo, 'checkout', '-q', '-b', 'fix/many')
        commit(repo, {'a.py': '1\n', 'b.py': '2\n', 'c.py': '3\n', 'docs/devflow/reports/r.md': 'r\n'})
        self.assertTrue(self.check(repo, baseline, exp)[0])
        commit(repo, {'d.py': '4\n'})
        ok, detail = self.check(repo, baseline, exp)
        self.assertFalse(ok)
        self.assertIn('fix/many', detail)

    def test_path_absent_and_present(self):
        repo, baseline = self.build()
        absent = {'type': 'path_absent', 'path': 'docs/devflow'}
        present = {'type': 'path_present', 'path': 'docs/devflow/reports/', 'on_branch_prefix': 'fix/'}
        self.assertTrue(self.check(repo, baseline, absent)[0])
        self.assertFalse(self.check(repo, baseline, present)[0])
        (repo / 'docs' / 'devflow').mkdir(parents=True)
        (repo / 'docs' / 'devflow' / 'x.md').write_text('x', encoding='utf-8')
        self.assertFalse(self.check(repo, baseline, absent)[0])
        self.assertTrue(self.check(repo, baseline, {'type': 'path_present', 'path': 'docs/devflow/x.md'})[0])
        git(repo, 'checkout', '-q', '-b', 'fix/r')
        commit(repo, {'docs/devflow/reports/r.md': 'r\n'})
        (repo / 'docs' / 'devflow' / 'x.md').unlink()
        self.assertTrue(self.check(repo, baseline, present)[0])
        ok, detail = self.check(repo, baseline, absent)
        self.assertFalse(ok)
        self.assertIn('fix/r', detail)

    def test_worktree_clean_and_user_change_preserved(self):
        repo, baseline = self.build('lite-dirty-checkout')
        content = scenario('lite-dirty-checkout')['fixture']['dirty']['README.md']
        preserved = {'type': 'user_change_preserved', 'path': 'README.md', 'content': content}
        self.assertFalse(self.check(repo, baseline, {'type': 'worktree_clean'})[0])
        self.assertTrue(self.check(repo, baseline, preserved)[0])
        git(repo, 'checkout', '--', 'README.md')
        self.assertTrue(self.check(repo, baseline, {'type': 'worktree_clean'})[0])
        self.assertFalse(self.check(repo, baseline, preserved)[0])
        (repo / 'README.md').unlink()
        self.assertFalse(self.check(repo, baseline, preserved)[0])

    def test_command_passes(self):
        repo, baseline = self.build()
        tests = {'type': 'command_passes', 'command': ['{python}', '-m', 'unittest', '-q']}
        self.assertFalse(self.check(repo, baseline, tests)[0])  # fixture bug: IVA missing
        on_fix = dict(tests, on_branch_prefix='fix/')
        self.assertFalse(self.check(repo, baseline, on_fix)[0])  # no branch yet
        git(repo, 'checkout', '-q', '-b', 'fix/iva')
        commit(repo, {'calc.py': FIXED_CALC})
        git(repo, 'checkout', '-q', 'main')
        self.assertTrue(self.check(repo, baseline, on_fix)[0])
        self.assertEqual(git(repo, 'status', '--porcelain'), '')
        missing = {'type': 'command_passes', 'command': ['definitely-not-a-binary-xyz']}
        self.assertFalse(self.check(repo, baseline, missing)[0])

    def test_transcript_and_remote(self):
        repo, baseline = self.build()
        exp = {'type': 'transcript_contains_any', 'patterns': ['Nivel FULL', 'completo']}
        self.assertTrue(self.check(repo, baseline, exp, 'elijo nivel full porque...')[0])
        self.assertFalse(self.check(repo, baseline, exp, 'lite')[0])
        self.assertTrue(self.check(repo, baseline, {'type': 'no_remote_push'})[0])
        git(repo, 'remote', 'add', 'origin', str(self.root / 'remote.git'))
        self.assertFalse(self.check(repo, baseline, {'type': 'no_remote_push'})[0])

    # ---- agent command construction and CLI

    def args(self, **kw):
        values = dict(runner='claude', runner_cmd=None, permission_mode='acceptEdits', allowed_tools='',
                      model=None, allow_skip_permissions=False)
        values.update(kw)
        return SimpleNamespace(**values)

    def test_build_command_safety(self):
        repo = self.root / 'r'
        argv = ev.build_command(self.args(model='sonnet'), '/pol-devflow help', repo)
        self.assertEqual(argv[:3], ['claude', '-p', '/pol-devflow help'])
        self.assertIn('acceptEdits', argv)
        self.assertNotIn('--dangerously-skip-permissions', argv)
        with self.assertRaises(ValueError):
            ev.build_command(self.args(permission_mode='bypassPermissions'), 'p', repo)
        with self.assertRaises(ValueError):
            ev.build_command(self.args(runner_cmd='claude --dangerously-skip-permissions -p {prompt}'), 'p', repo)
        argv = ev.build_command(self.args(allow_skip_permissions=True), 'p', repo)
        self.assertIn('--dangerously-skip-permissions', argv)
        codex = ev.build_command(self.args(runner='codex'), '/pol-devflow help', repo)
        self.assertEqual(codex[-1], '$pol-devflow help')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', codex)
        custom = ev.build_command(self.args(runner_cmd='["my agent", "--ask", "{prompt}"]'), 'a b', repo)
        self.assertEqual(custom, ['my agent', '--ask', 'a b'])

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(RUNNER), '--out', str(self.root / 'out'), *args],
                              capture_output=True, text=True, encoding='utf-8')

    def test_dry_run_never_invokes_agent(self):
        result = self.run_cli('--dry-run', '--runner-cmd', 'nonexistent-agent-binary-xyz {prompt}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('nonexistent-agent-binary-xyz', result.stdout)
        self.assertEqual(result.stdout.count('cwd='), len(ev.load_scenarios()))
        out = self.root / 'out'
        self.assertEqual(list(out.rglob('transcript.txt')), [])
        self.assertFalse(any((out / s['id'] / 'repo').exists() for s in ev.load_scenarios()))
        data = json.loads((out / 'results.json').read_text(encoding='utf-8'))
        self.assertTrue(data['dry_run'])
        self.assertTrue(all(row['status'] == 'DRY' for row in data['scenarios']))

    def test_missing_agent_binary_reports_error(self):
        result = self.run_cli('--scenario', 'plan-only', '--runner-cmd', 'nonexistent-agent-binary-xyz {prompt}')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        data = json.loads((self.root / 'out' / 'results.json').read_text(encoding='utf-8'))
        self.assertEqual(data['scenarios'][0]['status'], 'ERROR')

    def test_refuses_output_inside_git_repo(self):
        if not ev._inside_git_worktree(ROOT):
            self.skipTest('package is not a git checkout')
        result = subprocess.run([sys.executable, str(RUNNER), '--dry-run', '--out', str(ROOT / 'evals' / '_tmp_out')],
                                capture_output=True, text=True, encoding='utf-8')
        try:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('inside a git work tree', result.stderr)
        finally:
            ev._rmtree(ROOT / 'evals' / '_tmp_out')


if __name__ == '__main__':
    unittest.main()
