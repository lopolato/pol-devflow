import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, package, storage


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.homes = {'codex': self.root / 'codex', 'claude': self.root / 'claude'}

    def install(self, runtime='codex'):
        return package.install(self.data, runtime, self.homes[runtime])

    def test_install_only_owned_files_and_idempotent(self):
        home = self.homes['codex']
        home.mkdir()
        unrelated = home / 'config.toml'
        unrelated.write_text('model = "user-model"\n')
        self.install()
        self.assertTrue((home / 'skills/pol-devflow/SKILL.md').is_file())
        self.assertTrue((home / 'agents/pol-reviewer.toml').is_file())
        self.install()
        self.assertEqual(unrelated.read_text(), 'model = "user-model"\n')

    def test_name_conflict_rejected_without_overwrite(self):
        target = self.homes['codex'] / 'skills/pol-devflow/SKILL.md'
        target.parent.mkdir(parents=True)
        target.write_text('existing user skill')
        with self.assertRaises(storage.DevFlowError):
            self.install()
        self.assertEqual(target.read_text(), 'existing user skill')
        self.assertFalse((self.data / 'config/models.yaml').exists())

    def test_config_conflict_detected_before_any_write(self):
        self.install()
        cfg = self.data / 'config/models.yaml'
        before = cfg.read_bytes()
        target = self.homes['codex'] / 'agents/pol-reviewer.toml'
        target.write_text(target.read_text(encoding='utf-8') + '\n# manual user change\n', encoding='utf-8')
        before_all = {p: p.read_bytes() for p in self.homes['codex'].rglob('*') if p.is_file()}
        with self.assertRaises(storage.DevFlowError):
            package.config_set(self.data, 'codex', 'reviewer', model='new-model')
        self.assertEqual(cfg.read_bytes(), before)
        self.assertEqual(before_all, {p: p.read_bytes() for p in self.homes['codex'].rglob('*') if p.is_file()})

    def test_config_set_regenerates_target_runtime_only(self):
        self.install('codex')
        self.install('claude')
        claude_file = self.homes['claude'] / 'agents/pol-reviewer.md'
        before = claude_file.read_bytes()
        package.config_set(self.data, 'codex', 'reviewer', model='new-model', effort='high')
        self.assertEqual(claude_file.read_bytes(), before)
        self.assertIn('new-model', (self.homes['codex'] / 'agents/pol-reviewer.toml').read_text(encoding='utf-8'))
        self.assertEqual(config.load(self.data / 'config/models.yaml')['profiles']['reviewer']['codex']['model'], 'new-model')
        package.uninstall(self.data, 'codex')
        self.assertFalse((self.homes['codex'] / 'agents/pol-reviewer.toml').exists())

    def test_failed_regeneration_keeps_previous_config(self):
        self.install()
        before = (self.data / 'config/models.yaml').read_bytes()
        with patch('devflow.package.adapters.render_all', side_effect=storage.DevFlowError('generation failed')):
            with self.assertRaises(storage.DevFlowError):
                package.config_set(self.data, 'codex', 'reviewer', model='new')
        self.assertEqual((self.data / 'config/models.yaml').read_bytes(), before)

    def test_uninstall_preserves_modified_and_unrelated_files(self):
        self.install()
        target = self.homes['codex'] / 'agents/pol-reviewer.toml'
        target.write_text('manual version')
        other = self.homes['codex'] / 'agents/unrelated.toml'
        other.write_text('other')
        result = package.uninstall(self.data, 'codex')
        self.assertIn(target.resolve(), [Path(p).resolve() for p in result['preserved']])
        self.assertEqual(target.read_text(), 'manual version')
        self.assertEqual(other.read_text(), 'other')
        self.assertTrue((self.data / 'config/models.yaml').exists())

    def test_manifest_traversal_rejected(self):
        self.install()
        manifest = self.data / 'installations/codex.json'
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['files']['../../outside'] = 'bad'
        manifest.write_text(json.dumps(value))
        with self.assertRaises(storage.DevFlowError):
            package.uninstall(self.data, 'codex')

    def test_claude_skill_explicit_only(self):
        self.install('claude')
        content = (self.homes['claude'] / 'skills/pol-devflow/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('disable-model-invocation: true', content.split('---')[1])

    def test_claude_upgrade_preserves_explicit_invocation(self):
        self.install('claude')
        self.install('claude')
        target = self.homes['claude'] / 'skills/pol-devflow/SKILL.md'
        content = target.read_text(encoding='utf-8')
        self.assertEqual(content.split('---')[1].count('disable-model-invocation: true'), 1)
        manifest = package.load_manifest(self.data, 'claude')
        self.assertEqual(storage.digest(target.read_bytes()), manifest['files']['skills/pol-devflow/SKILL.md'])

    def test_native_claude_entrypoint_can_be_adapted_again_without_duplicate_keys(self):
        portable = b'---\nname: pol-devflow\ndescription: test\n---\nbody\n'
        once = package.skill_for_runtime(portable, 'claude')
        twice = package.skill_for_runtime(once, 'claude')
        self.assertEqual(twice, once)

    def test_installed_validator_detects_portable_entrypoint_overwrite(self):
        self.install('claude')
        target = self.homes['claude'] / 'skills/pol-devflow/SKILL.md'
        portable = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_bytes()
        target.write_bytes(portable)
        result = subprocess.run([sys.executable, str(target.parent / 'scripts/validate.py'),
                                 '--data-dir', str(self.data)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('disable-model-invocation', result.stderr)

    def test_codex_upgrade_preserves_policy_and_validator_detects_its_removal(self):
        self.install('codex')
        self.install('codex')
        policy = self.homes['codex'] / 'skills/pol-devflow/agents/openai.yaml'
        self.assertIn('allow_implicit_invocation: false', policy.read_text())
        self.assertEqual(package.validate_installed(self.data, 'codex')['validation_scope'], 'installed_runtime')
        policy.write_text('policy:\n  allow_implicit_invocation: true\n')
        with self.assertRaises(storage.DevFlowError):
            package.validate_installed(self.data, 'codex')


if __name__ == '__main__':
    unittest.main()
