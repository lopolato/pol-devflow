import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import storage


class AtomicWriteRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / 'state.json'
        self.target.write_bytes(b'old')
        self.real_replace = os.replace

    def test_transient_lock_is_retried(self):
        calls = []

        def locked_twice(source, target):
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError(5, 'Acceso denegado')
            return self.real_replace(source, target)

        with patch.object(storage.os, 'replace', side_effect=locked_twice), patch.object(storage.time, 'sleep'):
            storage.atomic_write(self.target, b'new')
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.target.read_bytes(), b'new')
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ['state.json'])

    def test_persistent_lock_fails_without_partial_write(self):
        with patch.object(storage.os, 'replace', side_effect=PermissionError(5, 'Acceso denegado')), \
                patch.object(storage.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                storage.atomic_write(self.target, b'new')
        self.assertEqual(sleep.call_count, 5)
        self.assertEqual(self.target.read_bytes(), b'old')
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ['state.json'])


if __name__ == '__main__':
    unittest.main()
