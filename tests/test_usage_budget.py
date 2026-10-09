import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UsageBudgetTests(unittest.TestCase):
    """Feature usage counters and the user-approved run budget (1.0.17)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.make_repo('repo')

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(repo, *args)
        (repo / 'app.py').write_bytes(b'original\n')
        self.git(repo, 'add', 'app.py')
        self.git(repo, 'commit', '-m', 'initial')
        return repo

    def git(self, repo, *args):
        return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, *args, repo=None, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(repo or self.repo), *args], capture_output=True, text=True,
                                encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def start(self, *extra, mode='feature', runtime='claude', repo=None):
        return self.cli('_run', 'start', '--mode', mode, '--request', 'Usage task', '--criterion', 'c1',
                        '--runtime', runtime, '--owner', 'co', *extra, repo=repo)

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_bytes(self, run):
        return (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()

    def features(self, run):
        return self.run_cli('show', run)['run']['features']

    def done(self, run, task, worker='w-1'):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.update(status='done', worker_id=worker, summary='mapped')
        return result

    def lite_record(self, record):
        return json.loads((self.data / 'lite' / (record['id'] + '.json')).read_text(encoding='utf-8'))

    # A1. Automatic features ----------------------------------------------------------------

    def test_full_run_records_automatic_features_and_read_only_helpers_keep_state_bytes(self):
        run = self.start()
        self.assertEqual(run['features'], ['level:full'])
        first = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--budget-minutes', '5')
        self.assertEqual(self.features(run), ['budget_minutes', 'level:full'])
        before = self.state_bytes(run)
        result = self.done(run, first)
        self.assertTrue(self.run_cli('record', run, '--dry-run', '--input', self.write('r.json', result))['valid'])
        self.run_cli('check-close', run)
        # Read-only helpers never rewrite state.json; their use is still counted.
        self.assertEqual(self.state_bytes(run), before)
        self.assertEqual(self.features(run), ['budget_minutes', 'check_close', 'dry_run', 'level:full', 'template'])
        self.run_cli('record', run, '--input', self.write('r.json', result))
        self.run_cli('task', run, '--role', 'tester', '--objective', 'test', '--context-from', first['task_id'])
        (Path(run['workspace']) / 'app.py').write_bytes(b'changed\n')
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Checkpoint')
        saved = json.loads(self.state_bytes(run))
        self.assertEqual(saved['features'], ['budget_minutes', 'check_close', 'checkpoint', 'context_from',
                                             'dry_run', 'level:full', 'template'])

    def test_incident_nesting_orca_and_identity_warning(self):
        run = self.start(mode='error')
        self.assertNotIn('incident', run['features'])
        incident = {'symptom': 'Login returns 500', 'status': 'not_verified', 'evidence': 'seen in log'}
        self.run_cli('update', run, '--input', self.write('i.json', {'incident': incident}))
        self.assertIn('incident', self.features(run))
        self.run_cli('close', run, '--status', 'partial')
        nested = self.start(runtime='codex')
        self.run_cli('task', nested, '--role', 'tester', '--objective', 'Read', '--read-scope', './',
                     '--can-delegate', '--native-nesting-evidence', 'fixture declared capability',
                     '--native-max-workers', '4')
        self.assertIn('nesting', self.features(nested))
        orca_repo = self.make_repo('orca')
        orca = self.start('--executor', 'orca', repo=orca_repo)
        self.assertEqual(orca['features'], ['executor:orca', 'level:full'])
        github = self.make_repo('github')
        self.git(github, 'remote', 'add', 'origin', 'https://github.com/example/project.git')
        warned = self.start(repo=github)
        self.assertTrue(warned['identity']['warning'])
        self.assertEqual(warned['features'], ['identity_warning', 'level:full'])

    def test_lite_levels_and_lite_review_feature(self):
        plain = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', repo=self.make_repo('plain'))
        self.assertEqual(plain['features'], ['level:lite'])
        record = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', '--owner', 'co', '--review')
        self.assertEqual(record['features'], ['level:lite+review'])
        (self.repo / 'app.py').write_bytes(b'fixed\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', record['branch'],
                 '--path', 'app.py', '--message', 'Fix')
        self.cli('_lite', 'review-diff', '--lite', record['id'], '--owner', 'co', '--author-id', 'lite-1')
        review = {'worker_id': 'rev-1', 'verdict': 'passed', 'revision': self.git(self.repo, 'rev-parse', 'HEAD')}
        self.cli('_lite', 'review', '--lite', record['id'], '--owner', 'co', '--input', self.write('rv.json', review))
        self.assertEqual(self.lite_record(record)['features'], ['level:lite+review', 'review:lite'])

    # A1. Declared features ----------------------------------------------------------------

    def test_declared_features_accept_known_names_only(self):
        run = self.start()
        declared = self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'co', '--name', 'codegraph')
        self.assertEqual(declared['features'], ['codegraph', 'level:full'])
        self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'co', '--name', 'codegraph')
        self.assertEqual(self.features(run), ['codegraph', 'level:full'])
        for bad in (('--name', 'telemetry'), ('--name', 'level:full'), ()):
            self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'co', *bad, ok=False)
        self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'intruder', '--name', 'memory', ok=False)
        self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'co', '--name', 'memory',
                 '--role', 'tester', ok=False)
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', ok=False)
        self.assertEqual(self.features(run), ['codegraph', 'level:full'])
        lite_repo = self.make_repo('lite')
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', repo=lite_repo)
        self.cli('_metrics', 'feature', '--lite', lite['id'], '--name', 'profile_reused', repo=lite_repo)
        owned = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', '--owner', 'co',
                         repo=self.make_repo('owned'))
        self.cli('_metrics', 'feature', '--lite', owned['id'], '--name', 'rules', ok=False)
        self.cli('_metrics', 'feature', '--lite', owned['id'], '--owner', 'co', '--name', 'rules')
        self.assertEqual(self.lite_record(lite)['features'], ['level:lite', 'profile_reused'])
        self.assertEqual(self.lite_record(owned)['features'], ['level:lite', 'rules'])

    # A1. Global command log and stats --features -------------------------------------------

    def test_commands_log_only_state_changing_cleanup_without_paths_or_branch_names(self):
        self.cli('stats', '--features')
        self.assertFalse(self.data.exists())  # Read-only commands never create the data home.
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Secret branch name')
        self.cli('cleanup', '--into', 'main')
        self.cli('stats', '--all', '--since', '3')
        self.cli('stats', '--features', '--all')
        self.assertFalse((self.data / 'usage').exists())  # Previews and stats stay read-only.
        self.cli('cleanup', '--apply', '--into', 'main')
        log = (self.data / 'usage' / 'commands.jsonl').read_text(encoding='utf-8')
        lines = [json.loads(line) for line in log.splitlines()]
        self.assertEqual([(l['command'], l['flags']) for l in lines], [('cleanup', ['apply', 'into'])])
        self.assertTrue(all(set(l) == {'command', 'flags', 'at'} for l in lines))
        for private in (str(self.repo), self.repo.name, str(self.data), lite['branch'], 'secret', 'main'):
            self.assertNotIn(private.lower(), log.lower())

    def test_stats_features_counts_never_used_repository_filter_and_since(self):
        run = self.start()
        self.cli('_metrics', 'feature', '--run', run['run_id'], '--owner', 'co', '--name', 'codegraph')
        other = self.make_repo('other')
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', repo=other)
        self.cli('cleanup', '--apply')
        here = self.cli('stats', '--features')
        self.assertEqual(here['records'], 1)
        self.assertEqual(here['features']['level:full'], {'runs': 1, 'lite': 0})
        self.assertEqual(here['features']['codegraph'], {'runs': 1, 'lite': 0})
        self.assertEqual(here['features']['level:lite'], {'runs': 0, 'lite': 0})
        self.assertIn('level:lite', here['never_used'])
        self.assertIn('memory', here['never_used'])
        self.assertNotIn('level:full', here['never_used'])
        self.assertIsNone(here['commands'])
        self.assertIn('only included with --all', here['note'])
        everything = self.cli('stats', '--features', '--all')
        self.assertEqual(everything['records'], 2)
        self.assertEqual(everything['features']['level:lite'], {'runs': 0, 'lite': 1})
        self.assertNotIn('level:lite', everything['never_used'])
        self.assertEqual(everything['commands'], {'cleanup': {'count': 1, 'flags': {'apply': 1}}})
        self.assertNotIn('command:cleanup', everything['never_used'])
        # Old records and old command lines fall outside --since.
        path = self.data / 'lite' / (lite['id'] + '.json')
        path.write_text(json.dumps(self.lite_record(lite) | {'created_at': '2000-01-01T00:00:00+00:00'}),
                        encoding='utf-8')
        log = self.data / 'usage' / 'commands.jsonl'
        log.write_text('{"command": "cleanup", "flags": [], "at": "2000-01-01T00:00:00+00:00"}\nnot json\n',
                       encoding='utf-8')
        recent = self.cli('stats', '--features', '--all', '--since', '1')
        self.assertEqual(recent['records'], 1)
        self.assertIn('level:lite', recent['never_used'])
        self.assertIn('command:cleanup', recent['never_used'])
        self.cli('stats', '--features', '--since', '0', ok=False)

    # A2. Run budget -----------------------------------------------------------------------

    def test_max_workers_refuses_extra_assignment_until_user_raises_it(self):
        for bad in (('--max-workers', '0'), ('--max-tokens', '-5')):
            self.cli('_run', 'start', '--mode', 'feature', '--request', 'x', '--criterion', 'c1',
                     '--runtime', 'claude', '--owner', 'co', *bad, ok=False)
        run = self.start('--max-workers', '2', '--max-tokens', '1000')
        self.assertEqual(run['budget'], {'max_workers': 2, 'max_tokens': 1000, 'history': []})
        explorer = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        self.run_cli('task', run, '--role', 'tester', '--objective', 'test', '--max-workers', '5', ok=False)
        error = self.run_cli('task', run, '--role', 'tester', '--objective', 'test', ok=False)
        self.assertIn('Run budget reached: 2 workers assigned of max 2; ask the user before raising it', error)
        # Replacements count as assignments too.
        error = self.run_cli('task', run, '--role', 'explorer', '--objective', 'again', '--replaces',
                             explorer['task_id'], ok=False)
        self.assertIn('Run budget reached', error)
        before = self.state_bytes(run)
        for bad in ({'max_workers': 1, 'approved_by': 'user'}, {'max_workers': 2, 'approved_by': 'user'},
                    {'max_workers': 3}, {'max_workers': 3, 'approved_by': ' '}, {'approved_by': 'user'},
                    {'max_workers': 3, 'approved_by': 'user', 'extra': 1}, {'max_workers': '3', 'approved_by': 'u'},
                    {'max_tokens': 500, 'max_workers': 4, 'approved_by': 'user'}):
            self.run_cli('update', run, '--input', self.write('b.json', {'budget': bad}), ok=False)
        self.assertEqual(self.state_bytes(run), before)
        self.run_cli('update', run, '--input', self.write('b.json', {'budget': {'max_workers': 3, 'approved_by': 'user'}}))
        budget = self.run_cli('show', run)['run']['budget']
        self.assertEqual((budget['max_workers'], budget['max_tokens']), (3, 1000))
        self.assertEqual([(h['field'], h['previous'], h['new'], h['approved_by']) for h in budget['history']],
                         [('max_workers', 2, 3, 'user')])
        self.assertTrue(budget['history'][0]['at'])
        self.run_cli('task', run, '--role', 'tester', '--objective', 'test')
        self.assertIn('3 workers assigned of max 3',
                      self.run_cli('task', run, '--role', 'tester', '--objective', 'more', ok=False))
        unlimited = self.start(repo=self.make_repo('free'))
        self.assertEqual(unlimited['budget'], {'max_workers': None, 'max_tokens': None, 'history': []})

    def test_known_tokens_over_budget_are_reported_never_blocking(self):
        run = self.start('--max-tokens', '1000')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'coordinator', '--tokens', '700')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'explorer')
        shown = self.run_cli('show', run)['budget']
        self.assertEqual(shown, {'max_workers': None, 'workers_used': 0, 'max_tokens': 1000, 'tokens_known': 700,
                                 'exceeded': []})
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'coordinator', '--tokens', '800')
        self.assertEqual(self.run_cli('show', run)['budget']['exceeded'], ['max_tokens'])
        status = self.cli('status', '--run', run['run_id'])['budget']
        self.assertEqual((status['tokens_known'], status['exceeded']), (1500, ['max_tokens']))
        revision = self.run_cli('show', run)['run']['current_revision']
        criteria = {'criteria_results': [{'criterion': 'c1', 'status': 'passed', 'revision': revision,
                                          'evidence': 'scenario passed'}]}
        self.run_cli('update', run, '--input', self.write('c.json', criteria))
        check = self.run_cli('check-close', run)
        self.assertTrue(check['can_complete'])
        self.assertEqual(check['blockers'], [])
        self.assertEqual(check['budget']['exceeded'], ['max_tokens'])
        self.assertEqual(len(check['budget_warnings']), 1)
        self.assertIn('1500', check['budget_warnings'][0])
        self.assertEqual(self.run_cli('close', run, '--status', 'completed')['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
