import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import cleanup, gitops, state, storage


class PilotFixTests(unittest.TestCase):
    """Problems found in a real client pilot: incident gate, budgets, identity, result helpers, cleanup, lite."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / 'app.py').write_text('original\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')

    def git(self, *args, cwd=None, env=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True, capture_output=True,
                              text=True, env=env).stdout.strip()

    def cli(self, *args, ok=True, env=None):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True,
                                encoding='utf-8', env=env)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def start(self, mode='feature', **kwargs):
        return self.cli('_run', 'start', '--mode', mode, '--request', 'Pilot task', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co', **kwargs)

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_bytes(self, run):
        return (self.data / 'runs' / run['run_id'] / 'state.json').read_bytes()

    def pass_criterion(self, run):
        revision = self.run_cli('show', run)['run']['current_revision']
        update = {'criteria_results': [{'criterion': 'c1', 'status': 'passed', 'revision': revision,
                                        'evidence': 'scenario passed'}]}
        self.run_cli('update', run, '--input', self.write('criteria.json', update))

    def isolated_env(self):
        # No global/system identity: only the repository config counts.
        empty = self.root / 'empty.gitconfig'
        # Keep the line-ending policy the fixture was committed with, so the checkout stays clean.
        autocrlf = subprocess.run(['git', 'config', '--get', 'core.autocrlf'], cwd=self.repo,
                                  capture_output=True, text=True).stdout.strip()
        empty.write_text(f'[core]\n\tautocrlf = {autocrlf}\n' if autocrlf else '')
        return dict(os.environ, GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM='1')

    # A. Incident traceability ------------------------------------------------------------

    def test_error_run_cannot_complete_until_incident_is_resolved_or_accepted(self):
        run = self.start('error')
        self.pass_criterion(run)
        self.assertIsNone(self.run_cli('show', run)['run']['incident'])
        check = self.run_cli('check-close', run)
        self.assertFalse(check['can_complete'])
        self.assertIn('Reported incident not verified as resolved', ' '.join(check['blockers']))
        self.assertIn('Reported incident not verified', self.run_cli('close', run, '--status', 'completed', ok=False))
        for status in ('not_verified', 'different_cause'):
            incident = {'symptom': 'Login returns 500', 'status': status, 'evidence': 'still seen in staging log'}
            self.run_cli('update', run, '--input', self.write('i.json', {'incident': incident}))
            self.assertIn('Reported incident not verified', self.run_cli('close', run, '--status', 'completed', ok=False))
        for bad in ({'symptom': 'x', 'status': 'resolved', 'evidence': 'y', 'extra': 1},
                    {'symptom': ' ', 'status': 'resolved', 'evidence': 'y'},
                    {'symptom': 'x', 'status': 'fixed', 'evidence': 'y'},
                    {'symptom': 'x', 'status': 'resolved', 'evidence': ''},
                    {'symptom': 'x', 'status': 'accepted_unverified', 'evidence': 'y'},
                    {'symptom': 'x', 'status': 'accepted_unverified', 'evidence': 'y', 'accepted_by': ''},
                    'resolved'):
            self.run_cli('update', run, '--input', self.write('bad.json', {'incident': bad}), ok=False)
        accepted = {'symptom': 'Login returns 500', 'status': 'accepted_unverified',
                    'evidence': 'no production access', 'accepted_by': 'user'}
        self.run_cli('update', run, '--input', self.write('i.json', {'incident': accepted}))
        self.assertTrue(self.run_cli('check-close', run)['can_complete'])
        resolved = {'symptom': 'Login returns 500', 'status': 'resolved', 'evidence': 'reproduction now returns 200'}
        self.run_cli('update', run, '--input', self.write('i.json', {'incident': resolved}))
        shown = self.run_cli('show', run)['run']
        self.assertEqual(shown['incident']['status'], 'resolved')
        self.assertEqual([i['status'] for i in shown['incident_history']],
                         ['not_verified', 'different_cause', 'accepted_unverified'])
        closed = self.run_cli('close', run, '--status', 'completed')
        self.assertEqual(closed['status'], 'completed')

    def test_incident_rule_only_applies_to_error_mode(self):
        run = self.start('feature')
        self.pass_criterion(run)
        check = self.run_cli('check-close', run)
        self.assertEqual((check['can_complete'], check['blockers'], check['budget_warnings']), (True, [], []))

    # B. Worker budget -------------------------------------------------------------------

    def test_task_budget_reports_overdue_without_mutating_state(self):
        run = self.start()
        task = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--budget-minutes', '5')
        self.assertEqual(task['budget_minutes'], 5)
        self.assertTrue(task['assigned_at'])
        other = self.run_cli('task', run, '--role', 'tester', '--objective', 'probe')
        self.assertIsNone(other['budget_minutes'])
        self.assertEqual(self.run_cli('show', run)['overdue_tasks'], [])
        self.run_cli('task', run, '--role', 'explorer', '--objective', 'x', '--budget-minutes', '0', ok=False)
        self.run_cli('refresh', run, '--budget-minutes', '3', ok=False)
        path = self.data / 'runs' / run['run_id'] / 'state.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=12)
        for item in value['tasks']:
            item['assigned_at'] = past.isoformat()
        path.write_text(json.dumps(value, indent=2), encoding='utf-8')
        before = path.read_bytes()
        overdue = self.run_cli('show', run)['overdue_tasks']
        self.assertEqual(len(overdue), 1)
        self.assertEqual((overdue[0]['task_id'], overdue[0]['role'], overdue[0]['budget_minutes']),
                         (task['task_id'], 'explorer', 5))
        self.assertGreaterEqual(overdue[0]['minutes_elapsed'], 12)
        self.assertEqual(self.cli('status', '--run', run['run_id'])['overdue_tasks'], overdue)
        self.assertEqual(path.read_bytes(), before)

    # C. Git identity --------------------------------------------------------------------

    def test_identity_warns_for_private_email_on_github_remote(self):
        env = self.isolated_env()
        self.git('remote', 'add', 'origin', 'https://github.com/acme/app.git')
        self.git('config', 'user.email', 'pilot@gmail.com')
        value = self.cli('_git', 'identity', '--workspace', str(self.repo), env=env)
        self.assertEqual((value['name'], value['email'], value['remotes']), ('DevFlow Test', 'pilot@gmail.com', ['origin']))
        self.assertTrue(value['github_remote'])
        self.assertFalse(value['noreply'])
        self.assertIn('GitHub may reject pushes from a private email', value['warning'])
        self.git('config', 'user.email', '123+pilot@users.noreply.github.com')
        value = self.cli('_git', 'identity', '--workspace', str(self.repo), env=env)
        self.assertTrue(value['noreply'])
        self.assertIsNone(value['warning'])
        run = self.start()
        self.assertEqual(run['identity']['email'], '123+pilot@users.noreply.github.com')
        self.assertNotIn('identity', self.run_cli('show', run)['run'])

    def test_missing_identity_is_reported_not_fatal(self):
        env = self.isolated_env()
        self.git('config', '--unset', 'user.name')
        self.git('config', '--unset', 'user.email')
        value = self.cli('_git', 'identity', '--workspace', str(self.repo), env=env)
        self.assertEqual((value['name'], value['email'], value['github_remote'], value['remotes']),
                         (None, None, False, []))
        self.assertIn('not configured', value['warning'])
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', env=env)
        self.assertIn('not configured', lite['identity']['warning'])

    def test_author_override_applies_to_one_commit_without_writing_config(self):
        config_before = (self.repo / '.git/config').read_bytes()
        lite = self.cli('_lite', 'start', '--mode', 'feature', '--request', 'Phone')
        (self.repo / 'app.py').write_text('changed\n')
        common = ('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', lite['branch'],
                  '--path', 'app.py', '--message', 'Phone')
        self.cli(*common, '--author-name', 'Pilot Bot', ok=False)
        self.cli(*common, '--author-email', 'bot@users.noreply.github.com', ok=False)
        self.cli(*common, '--author-name', 'Pilot Bot', '--author-email', 'not-an-email', ok=False)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.cli(*common, '--author-name', 'Pilot Bot', '--author-email', 'bot@users.noreply.github.com')
        self.assertEqual(self.git('log', '-1', '--format=%an|%ae|%cn|%ce'),
                         'Pilot Bot|bot@users.noreply.github.com|Pilot Bot|bot@users.noreply.github.com')
        self.assertEqual((self.repo / '.git/config').read_bytes(), config_before)
        self.assertEqual(self.git('config', 'user.email'), 'devflow@example.invalid')
        with self.assertRaises(storage.DevFlowError):
            gitops.author_options('Pilot\nBot', 'bot@example.invalid')

    def test_checkpoint_accepts_author_override(self):
        run = self.start()
        workspace = Path(run['workspace'])
        (workspace / 'app.py').write_text('changed\n')
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'x', '--author-email', 'a@b.c', ok=False)
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Change', '--author-name', 'Pilot Bot',
                     '--author-email', 'bot@users.noreply.github.com')
        self.assertEqual(self.git('log', '-1', '--format=%an|%ae', cwd=workspace),
                         'Pilot Bot|bot@users.noreply.github.com')
        self.assertEqual(self.git('config', 'user.name', cwd=workspace), 'DevFlow Test')

    # D. Result contract helpers ---------------------------------------------------------

    def test_template_returns_result_skeleton_read_only(self):
        run = self.start()
        explorer = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        reviewer = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        before = self.state_bytes(run)
        value = self.run_cli('template', run, '--task-id', explorer['task_id'])
        self.assertEqual(value, {'schema_version': 1, 'run_id': run['run_id'], 'task_id': explorer['task_id'],
                                 'role': 'explorer', 'worker_id': '', 'status': 'partial', 'summary': '',
                                 'observed_revision': explorer['candidate_revision'], 'result_revision': None,
                                 'workspace_dirty': False, 'files_changed': [], 'criteria_results': [],
                                 'findings': [], 'files_inspected': [], 'commits': [], 'decisions': [],
                                 'validation': [], 'risks': [], 'out_of_scope': [], 'questions': [],
                                 'next_action': '',
                                 'usage': {'model': None, 'tokens': None, 'duration_ms': None}})
        review = self.run_cli('template', run, '--task-id', reviewer['task_id'])
        self.assertEqual(review['review'], {'verdict': ''})
        self.cli('_run', 'template', '--run', run['run_id'], '--owner', 'intruder', '--task-id', explorer['task_id'],
                 ok=False)
        self.run_cli('template', run, '--task-id', 'task-missing', ok=False)
        self.assertEqual(self.state_bytes(run), before)

    def test_record_dry_run_validates_everything_without_saving(self):
        run = self.start()
        explorer = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        reviewer = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        result = self.run_cli('template', run, '--task-id', explorer['task_id'])
        result.update(status='done', worker_id='w-1', summary='mapped',
                      usage={'model': 'm', 'tokens': 10, 'duration_ms': 5})
        before = self.state_bytes(run)
        checked = self.run_cli('record', run, '--dry-run', '--input', self.write('r.json', result))
        self.assertTrue(checked['valid'])
        self.assertEqual(self.state_bytes(run), before)
        self.assertFalse((self.data / 'runs' / run['run_id'] / 'results').exists())
        for bad in ({'files_changed': ['app.py']}, {'worker_id': ''}, {'usage': {'tokens': -1}},
                    {'observed_revision': 'abc'}):
            self.run_cli('record', run, '--dry-run', '--input', self.write('bad.json', result | bad), ok=False)
        review = self.run_cli('template', run, '--task-id', reviewer['task_id'])
        review.update(worker_id='rev-1', summary='looked')
        error = self.run_cli('record', run, '--dry-run', '--input', self.write('rv.json', review), ok=False)
        self.assertIn('review.verdict', error)
        self.run_cli('record', run, '--input', self.write('rv.json', review), ok=False)
        self.assertEqual(self.state_bytes(run), before)
        review['review'] = {'verdict': 'passed', 'coverage': 'Inspected complete diff'}
        self.assertEqual(self.run_cli('record', run, '--dry-run', '--input', self.write('rv.json', review))
                         ['review_verdict'], 'passed')
        self.assertEqual(self.state_bytes(run), before)
        self.run_cli('show', run, '--dry-run', ok=False)
        self.run_cli('record', run, '--input', self.write('r.json', result))
        self.assertEqual(self.run_cli('show', run)['run']['tasks'][0]['status'], 'done')

    def test_reviewer_verdict_is_checked_before_mutation(self):
        run = self.start()
        reviewer = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
        result = self.run_cli('template', run, '--task-id', reviewer['task_id']) | {'worker_id': 'rev'}
        args = SimpleNamespace(action='record', run=run['run_id'], owner='co', input=self.write('rv.json', result),
                               role=None, dry_run=False, budget_minutes=None)
        ctx = SimpleNamespace(data_dir=str(self.data), root=str(ROOT), repo=str(self.repo))
        from devflow import cli
        saved, loads, real_load = [], [], state.load

        def load(*a):
            loads.append(real_load(*a))
            return loads[-1]

        with mock.patch.object(state, 'save', side_effect=lambda *a: saved.append(a)), \
                mock.patch.object(state, 'load', side_effect=load):
            with self.assertRaises(storage.DevFlowError):
                cli.run_command(args, ctx)
        loaded = loads[-1]
        self.assertEqual(saved, [])
        self.assertIsNone(loaded['tasks'][0]['result'])
        self.assertEqual(loaded['tasks'][0]['status'], 'pending')

    def test_check_close_lists_every_blocker(self):
        run = self.start()
        task = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.update(worker_id='w-1', status='cancelled', summary='stopped')
        self.run_cli('record', run, '--input', self.write('r.json', result))
        self.run_cli('update', run, '--input', self.write('u.json', {'required_checks': ['tests']}))
        before = self.state_bytes(run)
        check = self.run_cli('check-close', run)
        self.assertFalse(check['can_complete'])
        text = ' '.join(check['blockers'])
        self.assertGreaterEqual(len(check['blockers']), 3)
        self.assertIn('Acceptance criterion lacks current passing evidence: c1', text)
        self.assertIn(f"{task['task_id']} (explorer, cancelled)", text)
        self.assertIn('Required check lacks current evidence: tests', text)
        self.assertEqual(self.state_bytes(run), before)
        self.cli('_run', 'check-close', '--run', run['run_id'], '--owner', 'intruder', ok=False)
        error = self.run_cli('close', run, '--status', 'completed', ok=False)
        for expected in ('c1', task['task_id'], 'tests'):
            self.assertIn(expected, error)
        with self.assertRaises(storage.DevFlowError) as raised:
            state.assert_complete(state.load(self.data, run['run_id']))
        self.assertIn('Required check lacks current evidence: tests', str(raised.exception))
        self.assertIn('unfinished', str(raised.exception))

    # E. Cleanup -------------------------------------------------------------------------

    def items(self, result):
        return {item['branch']: item for item in result['items']}

    def test_cleanup_marks_content_equivalent_branch_but_keeps_it(self):
        lite = self.cli('_lite', 'start', '--mode', 'feature', '--request', 'Phone')
        (self.repo / 'app.py').write_text('phone\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', lite['branch'],
                 '--path', 'app.py', '--message', 'Phone')
        sha = self.git('rev-parse', 'HEAD')
        self.git('switch', 'main')
        other = self.cli('_lite', 'start', '--mode', 'feature', '--request', 'Other')
        (self.repo / 'other.txt').write_text('other\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', other['branch'],
                 '--path', 'other.txt', '--message', 'Other')
        self.git('switch', 'main')
        # Same patch rewritten with another author: different SHA, identical content.
        self.git('cherry-pick', sha)
        self.git('-c', 'user.name=Rewritten', '-c', 'user.email=1+r@users.noreply.github.com',
                 'commit', '--amend', '--no-edit', '--reset-author')
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), sha)
        listed = self.items(self.cli('cleanup'))
        item = listed[lite['branch']]
        self.assertTrue(item['equivalent'])
        self.assertFalse(item['merged'])
        self.assertEqual(item['action'], 'keep')
        self.assertIn('content identical to main with different SHA', ' '.join(item['reasons']))
        self.assertFalse(listed[other['branch']]['equivalent'])
        self.assertNotIn('content identical', ' '.join(listed[other['branch']]['reasons']))
        self.assertEqual(self.cli('cleanup', '--apply')['removed'], [])
        self.assertTrue(self.git('branch', '--list', lite['branch']))
        applied = self.cli('cleanup', '--apply', '--discard', lite['branch'])
        self.assertEqual([r['branch'] for r in applied['removed']], [lite['branch']])

    def test_failed_worktree_removal_is_recorded_as_residual(self):
        run = self.start()
        workspace, branch = Path(run['workspace']), run['branch']
        (workspace / 'app.py').write_text('feature\n')
        self.run_cli('checkpoint', run, '--path', 'app.py', '--message', 'Feature')
        self.run_cli('close', run, '--status', 'partial')
        self.git('merge', '--no-ff', '-m', 'merge', branch)
        real = gitops.git

        def failing(where, *args, **kwargs):
            if args[:2] == ('worktree', 'remove'):
                raise storage.DevFlowError('git worktree failed: Permission denied')
            return real(where, *args, **kwargs)

        with mock.patch.object(gitops, 'git', side_effect=failing):
            applied = cleanup.cleanup(self.data, self.repo, apply=True)
        self.assertEqual(applied['removed'], [])
        self.assertEqual(applied['errors'][0]['branch'], branch)
        self.assertEqual(applied['errors'][0]['residual'], [str(workspace)])
        self.assertTrue(workspace.exists())
        self.assertTrue(self.git('branch', '--list', branch))
        record = json.loads(next((self.data / 'worktrees/.devflow-ownership').glob('*.json')).read_text())
        self.assertEqual(record['residual_path'], str(workspace))
        self.assertIn('Permission denied', record['removal_error'])
        self.assertTrue(record['residual_at'])
        self.assertNotIn('removed_at', record)
        item = self.items(self.cli('cleanup'))[branch]
        self.assertEqual(item['action'], 'keep')
        self.assertEqual(item['residual'], [str(workspace)])
        self.assertIn(f'residual folder at {workspace}; inspect/remove manually', item['reasons'])
        self.assertEqual(self.cli('cleanup', '--apply')['removed'], [])
        self.assertTrue(workspace.exists())
        # Once the user removes the folder by hand, the merged branch becomes removable again.
        self.git('worktree', 'remove', str(workspace))
        item = self.items(self.cli('cleanup'))[branch]
        self.assertEqual((item['action'], item['residual']), ('remove', []))
        applied = self.cli('cleanup', '--apply')
        self.assertEqual([r['branch'] for r in applied['removed']], [branch])
        self.assertTrue(json.loads(next((self.data / 'worktrees/.devflow-ownership').glob('*.json'))
                                   .read_text())['removed_at'])

    # F. Lite with untracked files -------------------------------------------------------

    def test_lite_allows_unrelated_untracked_files_and_never_commits_them(self):
        (self.repo / 'notes.txt').write_text('local notes\n')
        (self.repo / 'drafts').mkdir()
        (self.repo / 'drafts/idea.md').write_text('idea\n')
        lite = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug')
        self.assertEqual(sorted(lite['untracked_preserved']), ['drafts/idea.md', 'notes.txt'])
        record = json.loads((self.data / 'lite' / (lite['id'] + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(sorted(record['untracked_preserved']), ['drafts/idea.md', 'notes.txt'])
        self.assertEqual(self.git('branch', '--show-current'), lite['branch'])
        (self.repo / 'app.py').write_text('fixed\n')
        self.cli('_git', 'commit', '--workspace', str(self.repo), '--expected-branch', lite['branch'],
                 '--path', 'app.py', '--message', 'Fix')
        self.assertEqual(self.git('show', '--name-only', '--format=', 'HEAD'), 'app.py')
        self.assertEqual((self.repo / 'notes.txt').read_text(), 'local notes\n')
        self.assertIn('?? notes.txt', self.git('status', '--porcelain'))

    def test_lite_still_refuses_tracked_or_staged_changes(self):
        (self.repo / 'notes.txt').write_text('local notes\n')
        (self.repo / 'app.py').write_text('user change\n')
        self.assertIn('clean checkout', self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', ok=False))
        self.git('checkout', '--', 'app.py')
        (self.repo / 'new.txt').write_text('staged\n')
        self.git('add', 'new.txt')
        self.assertIn('clean checkout', self.cli('_lite', 'start', '--mode', 'error', '--request', 'Bug', ok=False))
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.assertFalse((self.data / 'lite').exists())


if __name__ == '__main__':
    unittest.main()
