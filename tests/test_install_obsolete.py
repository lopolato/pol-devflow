import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import package

OBSOLETE = 'skills/pol-devflow/core/rules/retired-rule.md'


class InstallObsoleteTests(unittest.TestCase):
    """Upgrades drop owned files the new release no longer ships. Temp homes and package copies only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.data, self.home, self.source = base / 'data', base / 'codex', base / 'package'
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
        self.source.mkdir()
        for top in ('SKILL.md', 'README.md', 'VERIFICATION.md', 'agents', 'config', 'core', 'scripts', 'adapters'):
            path = ROOT / top
            if path.is_dir():
                shutil.copytree(path, self.source / top, ignore=ignore)
            elif path.is_file():
                shutil.copy2(path, self.source / top)
        self.retired = self.source / 'core/rules/retired-rule.md'
        self.retired.write_text('# Regla retirada\n\nTexto.\n', encoding='utf-8')
        self.target = self.home / OBSOLETE

    def install(self):
        return package.install(self.data, 'codex', self.home, self.source)

    def manifest(self):
        return json.loads((self.data / 'installations/codex.json').read_text(encoding='utf-8'))['files']

    def test_unmodified_obsolete_file_is_removed_on_upgrade(self):
        first = self.install()
        self.assertTrue(self.target.is_file())
        self.assertEqual((first['removed_obsolete'], first['preserved_modified']), ([], []))
        self.retired.unlink()
        result = self.install()
        self.assertEqual(result['removed_obsolete'], [str(self.target)])
        self.assertEqual(result['preserved_modified'], [])
        self.assertFalse(self.target.exists())
        self.assertNotIn(OBSOLETE, self.manifest())
        self.assertTrue((self.home / 'skills/pol-devflow/SKILL.md').is_file())
        self.assertEqual(package.validate_installed(self.data, 'codex')['verified_files'], len(self.manifest()))
        # Idempotent: nothing left to remove.
        self.assertEqual(self.install()['removed_obsolete'], [])

    def test_modified_obsolete_file_is_preserved_and_reported(self):
        self.install()
        self.target.write_text('# Mi versión local\n', encoding='utf-8')
        self.retired.unlink()
        result = self.install()
        self.assertEqual(result['removed_obsolete'], [])
        self.assertEqual(result['preserved_modified'], [str(self.target)])
        self.assertEqual(self.target.read_text(encoding='utf-8'), '# Mi versión local\n')
        self.assertIn(OBSOLETE, self.manifest())
        # Uninstall behaves as before: modified owned files stay and are reported.
        removed = package.uninstall(self.data, 'codex')
        self.assertEqual(removed['preserved'], [str(self.target)])
        self.assertTrue(self.target.is_file())
        self.assertFalse((self.home / 'skills/pol-devflow/SKILL.md').exists())

    def test_obsolete_file_already_deleted_is_forgotten(self):
        self.install()
        self.target.unlink()
        self.retired.unlink()
        result = self.install()
        self.assertEqual((result['removed_obsolete'], result['preserved_modified']), ([], []))
        self.assertNotIn(OBSOLETE, self.manifest())

    def test_uninstall_after_upgrade_removes_everything_owned(self):
        self.install()
        unrelated = self.home / 'agents/user-owned.toml'
        unrelated.write_text('user\n', encoding='utf-8')
        self.retired.unlink()
        self.install()
        result = package.uninstall(self.data, 'codex')
        self.assertEqual(result['preserved'], [])
        self.assertNotIn(str(self.target), result['removed'])
        self.assertFalse((self.data / 'installations/codex.json').exists())
        self.assertFalse((self.home / 'skills/pol-devflow/SKILL.md').exists())
        self.assertEqual(unrelated.read_text(encoding='utf-8'), 'user\n')


if __name__ == '__main__':
    unittest.main()
