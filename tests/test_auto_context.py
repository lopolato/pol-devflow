import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import profile

USAGE_MISSING = 'usage not recorded for this task'
EMPTY_CONTEXT = {'profile': {'source': None, 'codegraph': None}, 'codegraph': None, 'rules_count': 0, 'errors': []}


def rule(text, paths, kind='requirement'):
    return {'kind': kind, 'text': text, 'paths': paths}


class AutoContextTests(unittest.TestCase):
    """Context delivered by the CLI (start context, packet rules, record warnings, retro draft) and run hygiene."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.make_repo('repo')
        self.count = 0

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(repo, *args)
        for path in ('app.py', 'docs/guide.md', 'lib/other.py'):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_bytes(b'original\n')
        self.git(repo, 'add', '.')
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

    def write(self, value):
        self.count += 1
        path = self.root / f'input-{self.count}.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def start(self, *extra, repo=None):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'Context task', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co', *extra, repo=repo)

    def lite(self, repo):
        return self.cli('_lite', 'start', '--mode', 'error', '--request', 'Small bug', '--owner', 'co', repo=repo)

    def run_cli(self, action, run, *args, ok=True):
        return self.cli('_run', action, '--run', run['run_id'], '--owner', 'co', *args, ok=ok)

    def state_path(self, run):
        return self.data / 'runs' / run['run_id'] / 'state.json'

    def edit_state(self, run, change):
        value = json.loads(self.state_path(run).read_text(encoding='utf-8'))
        change(value)
        self.state_path(run).write_text(json.dumps(value), encoding='utf-8')
        return value

    def age(self, run, hours):
        stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()
        return self.edit_state(run, lambda value: value.update(updated_at=stamp))['updated_at']

    def template(self, run, task, **fields):
        result = self.run_cli('template', run, '--task-id', task['task_id'])
        result.update({'status': 'done', 'summary': 'done', 'worker_id': 'w-1', **fields})
        return result

    def add_rules(self, *entries, repo=None):
        return self.cli('_rules', 'add', '--input', self.write(list(entries)), repo=repo)

    # 2. Start context ---------------------------------------------------------------------------------

    def test_start_context_without_profile_rules_or_codegraph(self):
        run = self.start()
        self.assertEqual(run['context'], EMPTY_CONTEXT)
        self.assertNotIn('context', json.loads(self.state_path(run).read_text(encoding='utf-8')))
        record = self.lite(self.make_repo('lite'))
        self.assertEqual(record['context'], EMPTY_CONTEXT)
        stored = json.loads((self.data / 'lite' / (record['id'] + '.json')).read_text(encoding='utf-8'))
        self.assertNotIn('context', stored)

    def test_start_context_with_profile_rules_and_codegraph(self):
        lite_repo = self.make_repo('lite')
        for repo in (self.repo, lite_repo):
            (repo / '.codegraph').mkdir()
            (repo / '.codegraph' / 'codegraph.db').write_text('x')
            (repo / '.git' / 'info' / 'exclude').write_text('.codegraph/\n')
            self.cli('_profile', 'set', '--input', self.write({'commands': {'test': 'python -m unittest'}}),
                     repo=repo)
            self.add_rules(rule('Never log tokens', ['app.py'], 'must_not'), rule('Docs in Spanish', ['docs']),
                           repo=repo)
        for repo, output in ((self.repo, self.start()), (lite_repo, self.lite(lite_repo))):
            with self.subTest(repo=repo.name):
                context = output['context']
                self.assertEqual(context['errors'], [])
                self.assertEqual(context['rules_count'], 2)
                self.assertEqual(Path(context['codegraph']['project_path']).resolve(), repo.resolve())
                self.assertTrue(context['codegraph']['ignored_by_git'])
                self.assertEqual(context['profile']['source'], 'local')
                self.assertEqual(context['profile']['profile']['commands'], {'test': 'python -m unittest'})
                self.assertFalse(context['profile']['stale'])
                self.assertNotIn('next_action', context['profile'])

    def test_start_context_lookup_errors_never_fail_start(self):
        broken = profile.local_path(self.data, self.repo)
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text('{not json', encoding='utf-8')
        broken.with_suffix('.rules.json').write_text('{"schema_version": 7}', encoding='utf-8')
        for output in (self.start(), self.lite(self.repo)):
            context = output['context']
            self.assertIsNone(context['profile'])
            self.assertIsNone(context['codegraph'])
            self.assertEqual(context['rules_count'], 0)
            self.assertEqual(len(context['errors']), 2)
            self.assertTrue(context['errors'][0].startswith('profile: Cannot read JSON'))
            self.assertTrue(context['errors'][1].startswith('rules_count: Invalid project rules file'))

    # 2. Packet rules ----------------------------------------------------------------------------------

    def test_task_packets_include_rules_for_write_and_read_scope(self):
        added = self.add_rules(rule('Never log tokens', ['app.py'], 'must_not'), rule('Docs in Spanish', ['docs']),
                               rule('Keep helpers pure', ['lib/other.py'], 'convention'))['added']
        run = self.start()
        writer = self.run_cli('task', run, '--role', 'implementer', '--objective', 'change', '--write-scope', 'app.py',
                              '--read-scope', 'docs/guide.md')
        self.assertEqual([r['id'] for r in writer['rules']], [added[0]['id'], added[1]['id']])
        self.assertFalse(writer['rules_truncated'])
        self.assertNotIn('rules_error', writer)
        self.assertEqual(writer['rules'][0]['text'], 'Never log tokens')
        self.assertFalse(writer['rules'][0]['stale'])
        self.cancel(run, writer)
        reader = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--read-scope', 'lib/')
        self.assertEqual([r['id'] for r in reader['rules']], [added[2]['id']])
        whole = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--read-scope', './')
        self.assertEqual(len(whole['rules']), 3)
        none = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map', '--read-scope', 'missing.txt')
        self.assertEqual((none['rules'], none['rules_truncated']), ([], False))
        unscoped = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        self.assertNotIn('rules', unscoped)

    def test_packet_rules_are_truncated_at_twenty(self):
        self.add_rules(*[rule(f'Rule number {i}', ['app.py']) for i in range(21)])
        run = self.start()
        task = self.run_cli('task', run, '--role', 'implementer', '--objective', 'change', '--write-scope', 'app.py')
        self.assertEqual(len(task['rules']), 20)
        self.assertTrue(task['rules_truncated'])

    def test_packet_rules_lookup_error_is_reported_not_fatal(self):
        run = self.start()
        broken = profile.local_path(self.data, self.repo).with_suffix('.rules.json')
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text('{"schema_version": 7}', encoding='utf-8')
        task = self.run_cli('task', run, '--role', 'implementer', '--objective', 'change', '--write-scope', 'app.py')
        self.assertEqual(task['rules'], [])
        self.assertIn('Invalid project rules file', task['rules_error'])
        self.assertNotIn('rules_truncated', task)

    def cancel(self, run, task):
        self.run_cli('record', run, '--input', self.write(self.template(run, task, status='cancelled')))

    # 2. Record warnings -------------------------------------------------------------------------------

    def test_record_warns_when_usage_is_not_recorded(self):
        run = self.start()
        task = self.run_cli('task', run, '--role', 'explorer', '--objective', 'map')
        result = self.template(run, task)
        result.pop('usage')
        checked = self.run_cli('record', run, '--dry-run', '--input', self.write(result))
        self.assertEqual(checked['warnings'], [USAGE_MISSING])
        brief = {k: result[k] for k in ('run_id', 'task_id', 'worker_id', 'role', 'status', 'summary',
                                        'observed_revision', 'result_revision')}
        self.assertEqual(self.run_cli('record', run, '--dry-run', '--brief', '--task-id', task['task_id'],
                                      '--input', self.write(brief))['warnings'], [USAGE_MISSING])
        with_usage = result | {'usage': {'model': 'm', 'tokens': 10}}
        self.assertEqual(self.run_cli('record', run, '--dry-run', '--input', self.write(with_usage))['warnings'], [])
        recorded = self.run_cli('record', run, '--input', self.write(result))
        self.assertEqual(recorded['warnings'], [USAGE_MISSING])
        self.assertEqual(recorded['tasks'][0]['status'], 'done')
        # A separate _metrics declaration for the task also counts as recorded usage.
        other = self.run_cli('task', run, '--role', 'explorer', '--objective', 'again')
        self.cli('_metrics', 'add', '--run', run['run_id'], '--owner', 'co', '--role', 'explorer',
                 '--task-id', other['task_id'], '--tokens', '5')
        later = self.template(run, other)
        later.pop('usage')
        self.assertEqual(self.run_cli('record', run, '--input', self.write(later))['warnings'], [])

    # 2. check-close retro draft -------------------------------------------------------------------------

    def test_check_close_retro_draft_is_factual_and_never_written(self):
        run = self.start('--max-tokens', '5')
        draft = self.run_cli('check-close', run)['retro_draft']
        self.assertEqual(draft, {'went_well': [], 'problems': [{'category': 'tooling',
                                                                 'text': 'no usage metrics recorded'}],
                                 'suggestions': []})
        for worker in ('rev-1', 'rev-2'):
            task = self.run_cli('task', run, '--role', 'reviewer', '--objective', 'review')
            result = self.template(run, task, worker_id=worker, usage={'model': 'm', 'tokens': 10},
                                   review={'verdict': 'changes_required', 'coverage': 'Read the diff'})
            self.run_cli('record', run, '--input', self.write(result))
        fixer = self.run_cli('task', run, '--role', 'fixer', '--objective', 'fix', '--write-scope', 'app.py',
                             '--correction-key', 'k1', '--budget-minutes', '1', '--blockers-confirmed', 'Both real',
                             # A long digit run in the id once made _retro add reject the draft as a phone number.
                             '--task-id', 'task-1234567890')
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat()
        self.edit_state(run, lambda value: value['tasks'][-1].update(assigned_at=past))
        before = self.state_path(run).read_bytes()
        draft = self.run_cli('check-close', run)['retro_draft']
        self.assertEqual(draft, {'went_well': [], 'suggestions': [], 'problems': [
            {'category': 'process', 'text': '2 review rounds with changes_required'},
            {'category': 'process', 'text': '1 fixer tasks'},
            {'category': 'process', 'text': 'overdue tasks: 1 (fixer)'},
            {'category': 'process', 'text': 'budget warnings: max_tokens exceeded'}]})
        self.assertEqual(self.state_path(run).read_bytes(), before)
        self.assertNotIn('retro', self.run_cli('show', run)['run'])
        # The draft is directly acceptable by _retro add once the Coordinator completes it.
        saved = self.cli('_retro', 'add', '--run', run['run_id'], '--owner', 'co',
                         '--input', self.write(draft | {'suggestions': ['Confirm blockers earlier']}))
        self.assertEqual(saved['retro']['problems'], draft['problems'])

    # 3. Stale runs ------------------------------------------------------------------------------------

    def test_status_lists_stale_active_runs_of_this_repository(self):
        stale = self.start()
        stamp = self.age(stale, 30)
        unique = self.cli('status')
        self.assertEqual(unique['run']['run_id'], stale['run_id'])
        self.assertEqual(len(unique['stale_runs']), 1)
        item = unique['stale_runs'][0]
        self.assertEqual({k: item[k] for k in ('run_id', 'mode', 'updated_at')},
                         {'run_id': stale['run_id'], 'mode': 'feature', 'updated_at': stamp})
        self.assertGreaterEqual(item['hours_idle'], 30)
        self.assertLess(item['hours_idle'], 31)
        fresh = self.start()
        closed = self.start()
        self.run_cli('close', closed, '--status', 'partial')
        self.age(closed, 48)
        other_repo = self.make_repo('other')
        self.age(self.start(repo=other_repo), 48)
        listing = self.cli('status')
        self.assertEqual(len(listing['candidates']), 3)
        self.assertEqual([r['run_id'] for r in listing['stale_runs']], [stale['run_id']])
        self.assertNotIn(fresh['run_id'], [r['run_id'] for r in listing['stale_runs']])
        self.assertNotIn('stale_runs', self.cli('status', '--run', stale['run_id']))

    def test_abandon_stale_run_happy_path(self):
        run = self.start()
        self.age(run, 25)
        abandoned = self.cli('_run', 'abandon', '--run', run['run_id'], '--owner', 'new-session',
                             '--reason', 'Session lost after crash', '--confirm-stale')
        self.assertEqual(abandoned['status'], 'cancelled')
        self.assertEqual(abandoned['next_action'], 'Abandoned stale run; branch and worktree preserved')
        self.assertEqual({k: abandoned['abandoned'][k] for k in ('reason', 'by')},
                         {'reason': 'Session lost after crash', 'by': 'new-session'})
        self.assertIn('at', abandoned['abandoned'])
        self.assertEqual(abandoned['closed_at'], abandoned['updated_at'])
        self.assertEqual(abandoned['coordinator_id'], 'co')
        self.assertIn('abandon', abandoned['features'])
        self.assertTrue(Path(run['workspace']).is_dir())
        self.assertIn(run['branch'], self.git(self.repo, 'branch', '--list', run['branch']))
        self.assertEqual(self.cli('status')['stale_runs'], [])
        # Without --owner the abandonment is still recorded, with an unknown author.
        other = self.start()
        self.age(other, 25)
        anonymous = self.cli('_run', 'abandon', '--run', other['run_id'], '--reason', 'Gone', '--confirm-stale')
        self.assertIsNone(anonymous['abandoned']['by'])

    def test_abandon_refusals(self):
        run = self.start()
        before = self.state_path(run).read_bytes()
        error = self.cli('_run', 'abandon', '--run', run['run_id'], '--reason', 'Gone', '--confirm-stale', ok=False)
        self.assertIn('Run is not stale', error)
        self.assertEqual(self.state_path(run).read_bytes(), before)
        self.age(run, 30)
        before = self.state_path(run).read_bytes()
        error = self.cli('_run', 'abandon', '--run', run['run_id'], '--reason', 'Gone', ok=False)
        self.assertIn('--confirm-stale', error)
        for reason in ((), ('--reason', ''), ('--reason', 'two\nlines')):
            self.cli('_run', 'abandon', '--run', run['run_id'], *reason, '--confirm-stale', ok=False)
        self.cli('_run', 'close', '--run', run['run_id'], '--owner', 'co', '--status', 'partial',
                 '--confirm-stale', ok=False)
        self.cli('_run', 'close', '--run', run['run_id'], '--owner', 'co', '--status', 'partial',
                 '--reason', 'x', ok=False)
        self.cli('_run', 'abandon', '--run', 'missing-run', '--reason', 'Gone', '--confirm-stale', ok=False)
        self.assertFalse((self.data / 'runs' / 'missing-run').exists())
        self.assertEqual(self.state_path(run).read_bytes(), before)
        self.run_cli('close', run, '--status', 'partial')
        self.age(run, 30)
        error = self.cli('_run', 'abandon', '--run', run['run_id'], '--reason', 'Gone', '--confirm-stale', ok=False)
        self.assertIn('Only an active run can be abandoned (status: partial)', error)


if __name__ == '__main__':
    unittest.main()
