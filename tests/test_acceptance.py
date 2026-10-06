import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, gitops, package, state, storage


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.run = state.create(root / 'data', root, 'optimize', 'Reduce queries', config.defaults(),
                                branch='optimize/queries', revision='new', criteria=['query count improves'])
        self.run['criteria_results'] = [{'criterion': 'query count improves', 'status': 'passed',
                                        'revision': 'new', 'evidence': 'counted queries'}]

    def test_optimize_requires_comparable_objective_improvement(self):
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)
        measurement = {'metric': 'queries', 'procedure': 'same fixture request', 'evidence': 'request query log',
                       'before': 10, 'after': 4, 'direction': 'lower', 'before_revision': 'old', 'after_revision': 'new'}
        self.run['measurement'] = measurement
        state.assert_complete(self.run)
        for change in ({'after': 11}, {'after_revision': 'old'}, {'after': float('nan')}, {'before': True}):
            altered = copy.deepcopy(self.run)
            altered['measurement'].update(change)
            with self.assertRaises(storage.DevFlowError):
                state.assert_complete(altered)

    def test_unconfirmed_workers_and_blockers_prevent_completion(self):
        self.run['mode'] = 'error'
        self.run['workers'] = [{'worker_id': 'w', 'status': 'cancel_requested'}]
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)
        self.run['workers'][0]['status'] = 'cancelled_confirmed'
        self.run['findings'] = [{'kind': 'blocker', 'resolved': False}]
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)
        self.run['findings'][0]['resolved'] = True
        with self.assertRaises(storage.DevFlowError):
            state.assert_complete(self.run)
        self.run['findings'][0]['id'] = 'F1'
        self.run['validations'] = [dict(name='repro', revision='new', status='passed', procedure='repro', evidence='passed')]
        state.resolve_finding(self.run, dict(finding_id='F1', revision='new', evidence='fixed', check='repro'))
        # Error mode also needs the reported incident verified.
        state.record_incident(self.run, dict(symptom='query fails', status='resolved', evidence='repro passes'))
        state.assert_complete(self.run)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'feature/root')
        self.git('config', 'user.name', 'DevFlow Test')
        self.git('config', 'user.email', 'devflow@example.invalid')
        (self.repo / 'base.txt').write_text('base\n')
        self.git('add', 'base.txt')
        self.git('commit', '-m', 'base')

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_child_integration_and_conservative_cleanup(self):
        child = gitops.child(self.repo, 'child', self.root / 'trees')
        child_path = Path(child['workspace'])
        (child_path / 'child.txt').write_text('child\n')
        revision = gitops.commit(child_path, ['child.txt'], 'child checkpoint')
        with self.assertRaises(storage.DevFlowError):
            gitops.remove_integrated_child(self.repo, child_path)
        integrated = gitops.integrate(self.repo, child['branch'], 'feature/root')
        self.assertFalse(integrated['dirty'])
        self.assertEqual((self.repo / 'child.txt').read_text(), 'child\n')
        with self.assertRaises(storage.DevFlowError):
            gitops.remove_integrated_child(self.repo, child_path, workers_active=True)
        (child_path / 'pending.txt').write_text('pending\n')
        with self.assertRaises(storage.DevFlowError):
            gitops.remove_integrated_child(self.repo, child_path)
        (child_path / 'pending.txt').unlink()
        removed = gitops.remove_integrated_child(self.repo, child_path)
        self.assertFalse(child_path.exists())
        self.assertEqual(self.git('rev-parse', 'refs/heads/' + child['branch']), revision)


class RecoveryTests(unittest.TestCase):
    def test_config_write_failure_rolls_back_generated_agents_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, home = root / 'data', root / 'codex'
            package.install(data, 'codex', home)
            tracked = [data / 'config/models.yaml', data / 'installations/codex.json', *home.glob('agents/*.toml')]
            before = {p: p.read_bytes() for p in tracked}
            original = storage.atomic_write
            calls = [0]
            def fail_once(path, content):
                calls[0] += 1
                if calls[0] == 4:
                    raise OSError('simulated regeneration disk failure')
                return original(path, content)
            from unittest.mock import patch
            with patch.object(storage, 'atomic_write', side_effect=fail_once):
                with self.assertRaises(storage.DevFlowError):
                    package.config_set(data, 'codex', 'reviewer', model='new')
            self.assertEqual(before, {p: p.read_bytes() for p in tracked})


if __name__ == '__main__':
    unittest.main()
