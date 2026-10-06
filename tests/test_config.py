import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, adapters, storage


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = self.root / 'models.yaml'
        self.cfg.write_text(json.dumps(config.defaults()), encoding='utf-8')

    def test_defaults_inherit_and_coordinator_not_worker(self):
        value = config.load(self.cfg)
        self.assertEqual(set(value['profiles']), set(config.ROLES))
        for role in config.WORKER_ROLES:
            self.assertEqual(value['profiles'][role]['codex'], {})
        rendered = adapters.render_all('codex', value)
        self.assertEqual(len(rendered), 8)
        self.assertNotIn('pol-coordinator.toml', rendered)

    def test_set_preserves_other_profiles_and_inherit_clears_effort(self):
        before = config.load(self.cfg)
        after = config.changed(before, 'codex', 'reviewer', model='example', effort='high')
        expected = copy.deepcopy(before)
        expected['profiles']['reviewer']['codex'] = {'model': 'example', 'effort': 'high'}
        self.assertEqual(after, expected)
        inherited = config.changed(after, 'codex', 'reviewer', inherit=True)
        self.assertEqual(inherited, before)

    def test_invalid_selection_rejected(self):
        before = self.cfg.read_bytes()
        for args in [('codex', 'coordinator'), ('unknown', 'tester'), ('codex', 'missing')]:
            with self.assertRaises(storage.DevFlowError):
                config.changed(config.load(self.cfg), *args, model='x')
        with self.assertRaises(storage.DevFlowError):
            config.changed(config.load(self.cfg), 'claude', 'tester', model='x', effort='high')
        with self.assertRaises(storage.DevFlowError):
            config.changed(config.load(self.cfg), 'codex', 'tester', inherit=True, model='x')
        self.assertEqual(self.cfg.read_bytes(), before)

    def test_generated_native_formats_parse_and_inherit(self):
        import tomllib
        value = config.changed(config.load(self.cfg), 'codex', 'reviewer', model='a"b', effort='high')
        native = tomllib.loads(adapters.render_all('codex', value)['pol-reviewer.toml'])
        self.assertEqual(native['model'], 'a"b')
        self.assertEqual(native['name'], 'pol-reviewer')
        self.assertIn('task_id', native['developer_instructions'])
        self.assertIn('model: "inherit"', adapters.render_all('claude', value)['pol-reviewer.md'])

    def test_duplicate_json_keys_rejected(self):
        self.cfg.write_text('{"profiles": {}, "profiles": {}}', encoding='utf-8')
        with self.assertRaises(storage.DevFlowError):
            config.load(self.cfg)

    def test_legacy_eight_profiles_load_without_rewriting_models(self):
        value = config.defaults()
        del value['profiles']['lite']
        value['profiles']['reviewer']['codex'] = {'model': 'chosen', 'effort': 'high'}
        self.cfg.write_text(json.dumps(value), encoding='utf-8')
        before = self.cfg.read_bytes()
        loaded = config.load(self.cfg)
        self.assertEqual(loaded['profiles']['lite'], {'codex': {}, 'claude': {}})
        self.assertEqual(loaded['profiles']['reviewer']['codex'], value['profiles']['reviewer']['codex'])
        self.assertEqual(self.cfg.read_bytes(), before)

    def test_transaction_rolls_back_on_write_failure(self):
        a, b = self.root / 'a', self.root / 'b'
        a.write_bytes(b'old-a')
        b.write_bytes(b'old-b')
        original = storage.atomic_write
        calls = [0]
        def fail_once(path, content):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError('injected disk failure')
            return original(path, content)
        with patch.object(storage, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(storage.DevFlowError):
                storage.transaction({a: b'new-a', b: b'new-b'}, self.root / 'backups')
        self.assertEqual(a.read_bytes(), b'old-a')
        self.assertEqual(b.read_bytes(), b'old-b')
        self.assertTrue(list((self.root / 'backups').iterdir()))


if __name__ == '__main__':
    unittest.main()
