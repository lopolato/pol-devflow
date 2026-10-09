import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import metrics, state, storage


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        (repo / 'app.py').write_text('original\n')
        (repo / 'package.json').write_text('{"scripts": {"test": "node test.js"}}\n')
        self.git(repo, 'add', 'app.py', 'package.json')
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

    def start(self, repo=None):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'Phone', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co', repo=repo)

    # 1. Metrics -----------------------------------------------------------------

    def test_metrics_validate_and_never_invent_numbers(self):
        item = metrics.entry({'role': 'implementer', 'model': 'm', 'tokens': None})
        self.assertEqual(item['source'], 'unavailable')
        self.assertEqual(metrics.entry({'role': 'lite', 'tokens': 10})['source'], 'runtime')
        for bad in ({'role': 'nobody'}, {'role': 'tester', 'tokens': -1}, {'role': 'tester', 'tokens': 1.5},
                    {'role': 'tester', 'cost': 3}, {'role': 'tester', 'model': 'a\nb'},
                    {'role': 'tester', 'activity': 'compute'}):
            with self.assertRaises(storage.DevFlowError):
                metrics.entry(bad)

    def test_activity_stats_keep_unknown_legacy_and_wall_clock_separate(self):
        run = self.start()
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                 '--activity', 'implementation', '--duration-ms', '1200')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'reviewer', '--tokens', '100')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'tester',
                 '--activity', 'tests', '--duration-ms', '800')
        legacy = metrics.entry({'role': 'reviewer', 'duration_ms': 50})
        legacy.pop('activity')
        record = state.load(self.data, run['run_id'])
        record.setdefault('metrics', []).append(legacy)
        state.save(self.data, record, 'legacy metric fixture')
        stats = metrics.stats(self.data, self.repo)
        self.assertEqual(stats['activities']['implementation']['duration_ms'], 1200)
        self.assertEqual(stats['activities']['tests']['duration_known'], 1)
        self.assertEqual(stats['tasks']['full:feature']['tokens'], 100)
        self.assertEqual(stats['roles']['reviewer']['tokens'], 100)
        self.assertEqual(stats['total_tokens_known'], 100)
        self.assertNotIn('review', stats['activities'])
        self.assertEqual(stats['roles']['reviewer']['duration_ms'], 50)

    def test_prepare_result_expands_only_explicit_brief_facts_and_checks_ids(self):
        run = self.start()
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                        '--objective', 'small task')
        brief = {'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'worker-real',
                 'role': 'implementer', 'status': 'done', 'summary': 'No product changes',
                 'observed_revision': run['base_revision'], 'result_revision': None}
        prepared = self.cli('_run', 'prepare-result', '--run', run['run_id'], '--task-id', task['task_id'],
                            '--input', self.write('brief.json', brief))
        self.assertEqual(prepared['worker_id'], 'worker-real')
        self.assertEqual(prepared['criteria_results'], [])
        self.assertEqual(prepared['validation'], [])
        self.assertNotIn('usage', prepared)
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                 '--brief', '--input', self.write('brief-record.json', brief))
        bad_id = brief | {'task_id': 'task-wrong'}
        self.cli('_run', 'prepare-result', '--run', run['run_id'], '--task-id', task['task_id'],
                 '--input', self.write('bad-id.json', bad_id), ok=False)
        fabricated = brief | {'criteria_results': [{'criterion': 'invented', 'status': 'passed',
                                                     'revision': run['base_revision'], 'evidence': 'made up'}]}
        self.cli('_run', 'prepare-result', '--run', run['run_id'], '--task-id', task['task_id'],
                 '--input', self.write('fabricated.json', fabricated), ok=False)

    def test_brief_reviewer_can_record_explicit_review_and_usage_without_identity_bypass(self):
        run = self.start()
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'reviewer',
                        '--objective', 'review candidate')
        base = {'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'reviewer-real',
                'role': 'reviewer', 'status': 'done', 'summary': 'Inspected candidate',
                'observed_revision': run['base_revision'], 'result_revision': None,
                'review': {'verdict': 'passed', 'coverage': 'Inspected full diff and relevant code'},
                'usage': {'tokens': 44, 'duration_ms': 17}}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                 '--brief', '--input', self.write('bad-usage.json', base | {'usage': {'tokens': -1}}), ok=False)
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                 '--brief', '--input', self.write('usage-identity.json', base | {'usage': {'tokens': 1,
                                                                                           'worker_id': 'fake'}}), ok=False)
        unchanged = state.load(self.data, run['run_id'])
        self.assertIsNone(unchanged['tasks'][0]['result'])
        self.assertNotIn('metrics', unchanged)
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--task-id', task['task_id'],
                 '--brief', '--input', self.write('review-brief.json', base))
        saved = state.load(self.data, run['run_id'])
        self.assertEqual(saved['tasks'][0]['result']['review'], base['review'])
        self.assertEqual(saved['metrics'][0]['tokens'], 44)
        self.assertEqual(saved['metrics'][0]['worker_id'], 'reviewer-real')

    def test_incremental_review_needs_real_independent_coverage_and_keeps_full_diff(self):
        run = self.start()
        workspace = Path(run['workspace'])
        implementer = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                               '--objective', 'first change', '--write-scope', 'app.py')
        (workspace / 'app.py').write_text('changed once\n', encoding='utf-8')
        first_commit = self.cli('_git', 'commit', '--workspace', str(workspace), '--path', 'app.py',
                                '--message', 'first change')
        # The worktree is already committed; report it through the assigned write scope.
        implementation_result = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': implementer['task_id'],
                                 'worker_id': 'author-one', 'role': 'implementer', 'status': 'done',
                                 'summary': 'Changed app.py', 'observed_revision': run['base_revision'],
                                 'result_revision': first_commit['revision'], 'workspace_dirty': False,
                                 'files_changed': ['app.py'], 'commits': [first_commit['revision']]}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--input',
                 self.write('implementation.json', implementation_result))
        first_review = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'reviewer',
                                '--objective', 'full review')
        review_result = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': first_review['task_id'],
                         'worker_id': 'reviewer-one', 'role': 'reviewer', 'status': 'done',
                         'summary': 'Full diff inspected', 'observed_revision': first_commit['revision'],
                         'result_revision': None, 'workspace_dirty': False,
                         'review': {'verdict': 'passed', 'coverage': 'All changed paths and error handling inspected'}}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--input',
                 self.write('first-review.json', review_result))
        second_impl = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                               '--objective', 'test-only change', '--write-scope', 'test_app.py')
        (workspace / 'test_app.py').write_text('assert True\n', encoding='utf-8')
        second_commit = self.cli('_git', 'commit', '--workspace', str(workspace), '--path', 'test_app.py',
                                 '--message', 'second change')
        implementation_result = implementation_result | {'task_id': second_impl['task_id'], 'worker_id': 'author-two',
                                                          'observed_revision': first_commit['revision'],
                                                          'result_revision': second_commit['revision'],
                                                          'commits': [second_commit['revision']],
                                                          'files_changed': ['test_app.py']}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--input',
                 self.write('implementation2.json', implementation_result))
        self.assertEqual(self.cli('_run', 'show', '--run', run['run_id'])['run']['review']['revision'],
                         first_commit['revision'])
        delta_review = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'reviewer',
                                '--objective', 'review delta', '--review-from', first_review['task_id'])
        self.assertEqual(delta_review['review_delta']['base_revision'], first_commit['revision'])
        self.assertEqual(delta_review['review_diff']['base_revision'], run['base_revision'])
        delta_text = Path(delta_review['review_delta']['path']).read_text(encoding='utf-8')
        self.assertIn('test_app.py', delta_text)
        self.assertNotIn('changed once', delta_text)
        self.assertNotIn('review', delta_review)
        self.git(workspace, 'reset', '--hard', run['base_revision'])
        self.cli('_run', 'refresh', '--run', run['run_id'], '--owner', 'co')
        self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'reviewer',
                 '--objective', 'invalid stale delta', '--review-from', first_review['task_id'], ok=False)

    def test_usage_in_result_and_metrics_command_feed_stats(self):
        run = self.start()
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'explorer',
                        '--objective', 'map')
        # Minimal result: empty lists omitted (they default to []), usage recorded in the same call.
        result = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'w-1',
                  'role': 'explorer', 'status': 'done', 'summary': 'mapped', 'observed_revision': run['base_revision'],
                  'result_revision': None, 'workspace_dirty': False,
                  'usage': {'model': 'claude-sonnet-5-5', 'tokens': 1200, 'duration_ms': 30000}}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--input', self.write('r.json', result))
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'coordinator',
                 '--tokens', '800', '--phase', 'preflight')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'intruder', '--role', 'tester', ok=False)
        lite_repo = self.make_repo('lite')
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', repo=lite_repo)
        self.cli('_metrics', 'add', '--lite', lite['id'], '--role', 'lite', '--model', 'gpt-6-luna',
                 '--tokens', '300', repo=lite_repo)
        stats = self.cli('stats')
        self.assertEqual(stats['tasks']['full:feature']['count'], 1)
        self.assertEqual(stats['roles']['explorer']['tokens'], 1200)
        self.assertEqual(stats['roles']['explorer']['models'], {'claude-sonnet-5-5': 1})
        self.assertEqual(stats['roles']['coordinator']['tokens'], 800)
        self.assertNotIn('lite', stats['roles'])
        self.assertEqual(stats['total_tokens_known'], 2000)
        everything = self.cli('stats', '--all')
        self.assertEqual(everything['roles']['lite']['tokens'], 300)
        self.assertEqual(everything['total_tokens_known'], 2300)
        self.assertEqual(self.cli('stats', '--since', '1')['total_tokens_known'], 2000)
        self.cli('stats', '--since', '0', ok=False)

    def test_invalid_usage_rejects_the_record_without_partial_state(self):
        run = self.start()
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'explorer',
                        '--objective', 'map')
        result = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'w-1',
                  'role': 'explorer', 'status': 'done', 'summary': 'x', 'observed_revision': run['base_revision'],
                  'result_revision': None, 'workspace_dirty': False, 'usage': {'tokens': 'many'}}
        self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co', '--input', self.write('r.json', result),
                 ok=False)
        shown = self.cli('_run', 'show', '--run', run['run_id'])['run']
        self.assertIsNone(shown['tasks'][0]['result'])
        self.assertNotIn('metrics', shown)

    # 2. Project profile -----------------------------------------------------------

    def test_profile_is_local_by_default_and_detects_stale_dependencies(self):
        self.assertIsNone(self.cli('_profile', 'show')['source'])
        value = {'commands': {'test': 'npm test', 'lint': 'npm run lint'},
                 'verified': {'test': {'status': 'passed', 'revision': 'abc123'}}, 'notes': ['Node 22']}
        saved = self.cli('_profile', 'set', '--input', self.write('p.json', value))
        self.assertEqual(saved['source'], 'local')
        self.assertFalse(Path(saved['path']).is_relative_to(self.repo))
        self.assertEqual(self.git(self.repo, 'status', '--porcelain'), '')
        shown = self.cli('_profile', 'show')
        self.assertEqual(shown['profile']['commands']['test'], 'npm test')
        self.assertFalse(shown['stale'])
        # Merge keeps earlier commands; null removes one.
        self.cli('_profile', 'set', '--input', self.write('p2.json', {'commands': {'build': 'npm run build',
                                                                                   'lint': None}}))
        commands = self.cli('_profile', 'show')['profile']['commands']
        self.assertEqual(commands, {'test': 'npm test', 'build': 'npm run build'})
        (self.repo / 'package.json').write_text('{"scripts": {"test": "vitest"}}\n')
        shown = self.cli('_profile', 'show')
        self.assertTrue(shown['stale'])
        self.assertEqual(shown['changed_files'], ['package.json'])

    def test_profile_repo_file_has_priority_and_is_shared_data(self):
        self.cli('_profile', 'set', '--input', self.write('p.json', {'commands': {'test': 'local test'}}))
        saved = self.cli('_profile', 'set', '--repo-file', '--input',
                         self.write('r.json', {'commands': {'test': 'pytest -q'}}))
        self.assertTrue((self.repo / '.devflow/project.json').is_file())
        shown = self.cli('_profile', 'show')
        self.assertEqual(shown['source'], 'repository')
        self.assertEqual(shown['profile']['commands']['test'], 'pytest -q')
        self.assertIn('trust', shown)
        self.assertIn('ignored_local_profile', shown)
        self.assertIn('committed', saved['note'])

    def test_profile_is_shared_by_linked_worktrees_and_validated(self):
        self.cli('_profile', 'set', '--input', self.write('p.json', {'commands': {'test': 'npm test'}}))
        linked = self.root / 'linked'
        self.git(self.repo, 'worktree', 'add', '-q', '-b', 'other', str(linked))
        self.assertEqual(self.cli('_profile', 'show', repo=linked)['profile']['commands']['test'], 'npm test')
        for bad in ({'commands': {'deploy': 'x'}}, {'commands': {'test': 'a\nb'}}, {'shell': 'x'},
                    {'verified': {'test': {'status': 'ok', 'revision': 'r'}}}):
            self.cli('_profile', 'set', '--input', self.write('bad.json', bad), ok=False)
        self.cli('_profile', 'show', '--repo-file', ok=False)

    # 4. Fewer round trips -------------------------------------------------------------

    def test_checkpoint_commits_owned_paths_and_refreshes(self):
        run = self.start()
        workspace = Path(run['workspace'])
        (workspace / 'app.py').write_text('changed\n')
        (workspace / 'notes.txt').write_text('not mine\n')
        result = self.cli('_run', 'checkpoint', '--run', run['run_id'], '--owner', 'co', '--path', 'app.py',
                          '--message', 'Change app')
        self.assertTrue(result['workspace_dirty'])
        shown = self.cli('_run', 'show', '--run', run['run_id'])['run']
        self.assertEqual(shown['current_revision'], result['revision'])
        self.assertEqual(self.git(workspace, 'show', '--name-only', '--format=', 'HEAD'), 'app.py')
        self.cli('_run', 'checkpoint', '--run', run['run_id'], '--owner', 'other', '--path', 'notes.txt',
                 '--message', 'x', ok=False)
        self.cli('_run', 'checkpoint', '--run', run['run_id'], '--owner', 'co', '--message', 'x', ok=False)

    def test_omitted_files_changed_still_detects_real_changes(self):
        run = self.start()
        task = self.cli('_run', 'task', '--run', run['run_id'], '--owner', 'co', '--role', 'implementer',
                        '--objective', 'x', '--write-scope', 'app.py')
        (Path(run['workspace']) / 'app.py').write_text('changed\n')
        result = {'schema_version': 1, 'run_id': run['run_id'], 'task_id': task['task_id'], 'worker_id': 'w',
                  'role': 'implementer', 'status': 'done', 'summary': 'x', 'observed_revision': run['base_revision'],
                  'result_revision': None, 'workspace_dirty': True}
        error = self.cli('_run', 'record', '--run', run['run_id'], '--owner', 'co',
                         '--input', self.write('r.json', result), ok=False)
        self.assertIn('changed-file list', error)


if __name__ == '__main__':
    unittest.main()
