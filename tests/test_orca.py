import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import cli, config, state, orca, storage


class OrcaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.data = self.root / 'data'
        self.repo.mkdir()
        self.git('init', '-b', 'feature/test')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'app.py').write_text('value = 1\n')
        self.git('add', 'app.py')
        self.git('commit', '-m', 'initial')
        self.run = state.create(self.data, self.repo, 'feature', 'Add feature', config.defaults(),
                                'feature/test', self.git('rev-parse', 'HEAD'), ['works'], owner='co')
        self.run['executor'] = 'orca'
        state.save(self.data, self.run, 'test executor')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def call(self, *args, ok=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(['--data-dir', str(self.data), '--repo', str(self.repo),
                                 '--root', str(ROOT), *args])
            except SystemExit as exc:
                code = exc.code
        if ok:
            self.assertEqual(code, 0, err.getvalue())
            return json.loads(out.getvalue())
        self.assertNotEqual(code, 0, out.getvalue())
        return err.getvalue()

    def task(self, role, write=None, ok=True):
        extra = ['--write-scope', write] if write else []
        return self.call('_run', 'task', '--run', self.run['run_id'], '--owner', 'co',
                         '--role', role, '--objective', 'Inspect feature', *extra, ok=ok)

    def test_link_cannot_inject_settlement_or_accounting(self):
        task = self.task('explorer')
        value = {'orca_run_id': 'o1', 'orca_task_id': 'ot1', 'dispatch_id': 'd1',
                 'worker_id': 'orca:w1', 'agent_handle': 'w1', 'workspace': str(self.repo),
                 'runtime': 'codex', 'evidence': 'checked receipt'}
        for field in ('settlement', 'accounting', 'settled_at', 'linked_at'):
            self.bridge('link', task, value | {field: {'outcome': 'succeeded'}}, ok=False)
        self.bridge('link', task, value)
        run = state.load(self.data, self.run['run_id'])
        with self.assertRaises(storage.DevFlowError):
            orca.assert_complete(run)

    def test_fresh_orca_start_inherits_instead_of_packaged_models(self):
        started = self.call('_run', 'start', '--executor', 'orca', '--mode', 'feature', '--request', 'small',
                            '--criterion', 'works', '--owner', 'co', '--runtime', 'codex')
        run = state.load(self.data, started['run_id'])
        self.assertEqual(run['config_snapshot'], config.defaults())

    def test_lite_orca_cleanup_waits_for_runtime_accounting(self):
        record = self.call('_lite', 'start', '--executor', 'orca', '--owner', 'co',
                           '--mode', 'feature', '--request', 'small')
        self.git('switch', 'feature/test')
        preview = self.call('cleanup', '--purge-history', '--into', 'feature/test')
        item = next(i for i in preview['items'] if i['branch'] == record['branch'])
        self.assertEqual(item['action'], 'keep')
        self.assertTrue(any('Orca lite' in r for r in item['reasons']))
        link = {'orca_run_id': 'o1', 'orca_task_id': 'ot1', 'dispatch_id': 'd1',
                'worker_id': 'orca:w1', 'agent_handle': 'w1', 'workspace': str(self.repo),
                'runtime': 'codex', 'evidence': 'checked receipt'}
        value = self.root / 'lite-evidence.json'
        def mutate(action, evidence):
            value.write_text(json.dumps(evidence))
            return self.call('_lite', action, '--lite', record['id'], '--owner', 'co', '--input', str(value))
        mutate('link', link)
        settlement = {k: link[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')}
        mutate('settle', settlement | {'type': 'runtime_settled', 'outcome': 'failed',
                                      'proof': 'stopped', 'evidence': 'checked recovery'})
        mutate('account', {'dispatch_id': 'd1', 'action': 'released', 'evidence': 'release receipt'})
        preview = self.call('cleanup', '--purge-history', '--into', 'feature/test')
        item = next(i for i in preview['items'] if i['branch'] == record['branch'])
        self.assertEqual(item['action'], 'remove')

    def test_closed_partial_accepts_recovery_without_reopening(self):
        task = self.task('explorer')
        link = self.link(task)
        run = state.load(self.data, self.run['run_id'])
        run['status'] = 'partial'
        state.save(self.data, run, 'test closed')
        self.settle(task, link, 'failed')
        self.bridge('account', task, {'dispatch_id': 'd1', 'action': 'released', 'evidence': 'checked'})
        self.assertEqual(state.load(self.data, self.run['run_id'])['status'], 'partial')

    def test_lite_records_orca_retention_without_user_request(self):
        record = self.call('_lite', 'start', '--executor', 'orca', '--owner', 'co',
                           '--mode', 'feature', '--request', 'small')
        evidence_path = self.root / 'lite-retention.json'

        def mutate(action, value):
            evidence_path.write_text(json.dumps(value))
            return self.call('_lite', action, '--lite', record['id'], '--owner', 'co',
                             '--input', str(evidence_path))

        link = {'orca_run_id': 'o1', 'orca_task_id': 'ot1', 'dispatch_id': 'd1',
                'worker_id': 'orca:w1', 'agent_handle': 'w1', 'workspace': str(self.repo),
                'runtime': 'codex', 'evidence': 'checked receipt'}
        mutate('link', link)
        settlement = {k: link[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')}
        mutate('settle', settlement | {'type': 'worker_done', 'outcome': 'succeeded',
                                      'evidence': 'accepted matching completion'})
        mutate('account', {'dispatch_id': 'd1', 'action': 'retained', 'retention_source': 'orca',
                           'evidence': 'checked release receipt', 'orca_release_result': {
                               'dispatchId': 'd1', 'state': 'retained',
                               'reason': 'user_takeover', 'processAction': 'none'}})
        saved = storage.read_json(self.data / 'lite' / (record['id'] + '.json'))
        self.assertEqual(saved['status'], 'settled')
        self.assertEqual(saved['orca']['accounting']['action'], 'retained')
        self.assertNotIn('user_requested', saved['orca']['accounting'])
        self.assertEqual(self.git('branch', '--show-current'), record['branch'])

    def bridge(self, action, task, value=None, ok=True):
        extra = []
        if value is not None:
            p = self.root / 'bridge.json'
            p.write_text(json.dumps(value))
            extra = ['--input', str(p)]
        return self.call('_orca', action, '--run', self.run['run_id'], '--owner', 'co',
                         '--task-id', task['task_id'], *extra, ok=ok)

    def link(self, task, dispatch='d1', worker='worker-1'):
        value = {'orca_run_id': 'o1', 'orca_task_id': 'o-' + task['task_id'],
                 'dispatch_id': dispatch, 'worker_id': worker, 'workspace': str(self.repo),
                 'runtime': 'codex', 'agent_handle': worker, 'evidence': 'Coordinator checked worker-start receipt'}
        value['worker_id'] = 'orca:' + worker
        self.bridge('link', task, value)
        return value

    def settle(self, task, link, outcome='succeeded'):
        value = {k: link[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')}
        value.update(type='worker_done', outcome=outcome, evidence='Coordinator checked live Dispatch delivery')
        return self.bridge('settle', task, value)

    def record(self, task, worker, status='done', ok=True):
        p = self.root / 'result.json'
        result = state.empty_result(task, worker)
        result.update(status=status, summary='Inspected')
        p.write_text(json.dumps(result))
        return self.call('_run', 'record', '--run', self.run['run_id'], '--owner', 'co',
                         '--input', str(p), ok=ok)

    def test_read_wave_blocks_writers_until_every_reader_finishes(self):
        a, b = self.task('explorer'), self.task('architect')
        self.task('implementer', 'app.py', ok=False)
        self.task('tester', 'app.py', ok=False)
        for n, task in enumerate((a, b)):
            link = self.link(task, 'd' + str(n), 'worker-' + str(n))
            self.settle(task, link)
            self.record(task, link['worker_id'])
            if n == 0:
                self.task('implementer', 'app.py', ok=False)
        self.task('implementer', 'app.py')

    def test_native_assignments_stay_sequential(self):
        self.run.pop('executor')
        state.save(self.data, self.run, 'native')
        self.task('explorer')
        self.task('architect', ok=False)

    def test_orca_result_requires_matching_settlement_and_identity(self):
        task = self.task('explorer')
        self.record(task, 'orca:worker-1', ok=False)
        link = self.link(task)
        self.record(task, 'orca:worker-1', ok=False)
        stale = {k: link[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')}
        stale.update(type='worker_done', dispatch_id='old', outcome='succeeded', evidence='stale delivery')
        self.bridge('settle', task, stale, ok=False)
        self.settle(task, link)
        self.record(task, 'different-worker', ok=False)
        self.record(task, 'orca:worker-1')

    def test_failed_dispatch_cannot_accredit_done(self):
        task = self.task('explorer')
        link = self.link(task)
        self.settle(task, link, 'failed')
        self.record(task, link['worker_id'], ok=False)
        self.record(task, link['worker_id'], 'blocked')

    def test_spec_is_read_only_self_contained_and_uses_snapshot(self):
        self.run['config_snapshot']['profiles']['explorer']['codex'] = {'model': 'chosen', 'effort': 'high'}
        state.save(self.data, self.run, 'preferences')
        task = self.task('explorer')
        before = {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()}
        spec = self.bridge('spec', task)
        self.assertEqual(before, {p: p.read_bytes() for p in self.data.rglob('*') if p.is_file()})
        self.assertEqual(spec['launch_preferences'], {'model': 'chosen', 'effort': 'high'})
        self.assertEqual(Path(spec['workspace']), self.repo.resolve())
        self.assertIn(json.dumps(task['workspace']), spec['spec'])
        self.assertIn('worker_done', spec['spec'])
        self.assertIn('Context7', spec['spec'])

    def test_orca_start_keeps_current_checkout_and_dirty_start_has_no_effect(self):
        start = self.call('_run', 'start', '--executor', 'orca', '--mode', 'feature', '--runtime', 'codex',
                          '--owner', 'co', '--request', 'Small task', '--criterion', 'works')
        self.assertEqual(Path(start['workspace']), self.repo.resolve())
        self.assertEqual(start['executor'], 'orca')
        self.assertEqual(len(self.git('worktree', 'list').splitlines()), 1)
        (self.repo / 'app.py').write_text('user work\n')
        branch = self.git('branch', '--show-current')
        self.call('_run', 'start', '--executor', 'orca', '--mode', 'feature', '--runtime', 'codex',
                  '--owner', 'co', '--request', 'Other task', '--criterion', 'works', ok=False)
        self.assertEqual(self.git('branch', '--show-current'), branch)

    def test_accounting_required_and_retention_needs_user_request(self):
        task = self.task('explorer')
        link = self.link(task)
        self.settle(task, link)
        self.record(task, link['worker_id'])
        run = state.load(self.data, self.run['run_id'])
        with self.assertRaises(storage.DevFlowError):
            orca.assert_complete(run)
        value = {'dispatch_id': link['dispatch_id'], 'action': 'retained', 'evidence': 'retention'}
        self.bridge('account', task, value, ok=False)
        value.update(action='released', evidence='Coordinator verified Orca release receipt')
        self.bridge('account', task, value)
        orca.assert_complete(state.load(self.data, self.run['run_id']))

    def test_duplicate_dispatch_and_changed_run_rejected(self):
        a, b = self.task('explorer'), self.task('architect')
        link = self.link(a)
        duplicate = dict(link, orca_task_id='other')
        self.bridge('link', b, duplicate, ok=False)
        self.bridge('link', b, dict(duplicate, dispatch_id='d2', orca_run_id='wrong'), ok=False)
        self.bridge('link', b, dict(duplicate, dispatch_id='d2', worker_id='new-label'), ok=False)

    def test_cleanup_cannot_purge_unaccounted_orca_dispatch(self):
        self.git('branch', 'main')
        task = self.task('explorer')
        self.link(task)
        self.call('_run', 'close', '--run', self.run['run_id'], '--owner', 'co', '--status', 'partial')
        self.git('switch', 'main')
        result = self.call('cleanup', '--apply', '--purge-history')
        self.assertEqual(result['removed'], [])
        self.assertTrue((self.data / 'runs' / self.run['run_id'] / 'state.json').exists())

    def test_effort_without_model_is_not_forwarded_to_orca(self):
        self.run['config_snapshot']['profiles']['explorer']['codex'] = {'effort': 'high'}
        state.save(self.data, self.run, 'effort')
        task = self.task('explorer')
        self.assertEqual(self.bridge('spec', task)['launch_preferences'], {})

    def test_task_context_is_preserved_in_orca_spec_without_weakening_scopes(self):
        context = {'relevant_context': [{'library': 'example', 'version': '1.2', 'source': 'official',
                                        'conclusion': 'Use the installed API'}],
                   'constraints': ['Preserve behavior']}
        path = self.root / 'context.json'
        path.write_text(json.dumps(context))
        task = self.call('_run', 'task', '--run', self.run['run_id'], '--owner', 'co',
                         '--role', 'explorer', '--objective', 'Inspect API', '--input', str(path))
        spec = self.bridge('spec', task)
        self.assertIn('Use the installed API', spec['spec'])
        self.assertEqual(task['write_scope'], [])
        self.assertIn('No delegation; deliver to Coordinator; no push or merge main/master', task['constraints'])

    def test_snapshot_captures_managed_preferences_without_changing_config(self):
        from devflow import package
        home = self.root / 'codex-home'
        package.install(self.data, 'codex', home, ROOT)
        package.config_set(self.data, 'codex', 'explorer', model='selected-by-user', effort='high', root=ROOT)
        before = (self.data / 'config/models.yaml').read_bytes()
        snapshot = orca.snapshot_settings(self.data, config.defaults())
        self.assertEqual(snapshot['profiles']['explorer']['codex'],
                         {'model': 'selected-by-user', 'effort': 'high'})
        self.assertEqual((self.data / 'config/models.yaml').read_bytes(), before)
        (home / 'agents/pol-explorer.toml').write_text('manually changed')
        with self.assertRaises(storage.DevFlowError):
            orca.snapshot_settings(self.data, config.defaults())

    def test_reuse_requires_linked_followup_on_same_agent(self):
        a = self.task('explorer')
        link_a = self.link(a)
        self.settle(a, link_a)
        self.record(a, link_a['worker_id'])
        value = {'dispatch_id': 'd1', 'action': 'reused', 'next_dispatch_id': 'missing', 'evidence': 'reuse'}
        self.bridge('account', a, value, ok=False)
        b = self.task('architect')
        self.link(b, 'd2', 'worker-1')
        value['next_dispatch_id'] = 'd2'
        self.bridge('account', a, value)

    def test_orca_cannot_keep_a_second_native_activity_list(self):
        p = self.root / 'workers.json'
        p.write_text(json.dumps({'workers': [{'worker_id': 'invented', 'status': 'done'}]}))
        self.call('_run', 'update', '--run', self.run['run_id'], '--owner', 'co',
                  '--input', str(p), ok=False)

    def test_second_retry_uses_latest_failed_attempt(self):
        previous = self.task('explorer')
        common_task = 'one-orca-task'
        for n in range(3):
            value = {'orca_run_id': 'o1', 'orca_task_id': common_task, 'dispatch_id': 'retry-' + str(n),
                     'worker_id': 'orca:agent-' + str(n), 'agent_handle': 'agent-' + str(n),
                     'workspace': str(self.repo), 'runtime': 'codex', 'evidence': 'accepted receipt'}
            self.bridge('link', previous, value)
            self.settle(previous, value, 'failed')
            self.record(previous, value['worker_id'], 'blocked')
            if n < 2:
                previous = self.call('_run', 'task', '--run', self.run['run_id'], '--owner', 'co',
                                     '--role', 'explorer', '--objective', 'Retry', '--replaces', previous['task_id'])

    def test_positive_runtime_recovery_does_not_invent_worker_done(self):
        task = self.task('explorer')
        link = self.link(task)
        recovery = {k: link[k] for k in ('orca_run_id', 'orca_task_id', 'dispatch_id', 'worker_id')}
        recovery.update(type='runtime_settled', outcome='failed', proof='stopped',
                        evidence='Orca accepted worker-stop after positively observed exit')
        self.bridge('settle', task, recovery)
        self.record(task, link['worker_id'], 'blocked')

    def test_reuse_cannot_point_backwards(self):
        a = self.task('explorer')
        link_a = self.link(a)
        self.settle(a, link_a)
        self.record(a, link_a['worker_id'])
        b = self.task('architect')
        link_b = self.link(b, 'd2', 'worker-1')
        self.settle(b, link_b)
        self.record(b, link_b['worker_id'])
        self.bridge('account', b, {'dispatch_id': 'd2', 'action': 'reused', 'next_dispatch_id': 'd1',
                                   'evidence': 'old dispatch'}, ok=False)


if __name__ == '__main__':
    unittest.main()
