import argparse
import contextlib
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import retro, rules, storage


def run_module(data, repo, *argv):
    """In-process parser/dispatch with only the knowledge modules, as cli.py will hook them."""
    result = argparse.ArgumentParser(allow_abbrev=False)
    commands = result.add_subparsers(dest='command', required=True)
    retro.add_parsers(commands)
    rules.add_parsers(commands)
    args = result.parse_args(argv)
    ctx = SimpleNamespace(data_dir=str(data), repo=str(repo), root=str(ROOT))
    for module in (retro, rules):
        out = module.dispatch(args, ctx)
        if out is not None:
            return json.loads(json.dumps(out))
    raise AssertionError('No knowledge module handled ' + args.command)


def cli_hooked(command):
    """True once cli.py registers and dispatches the command (integration hook in place)."""
    from devflow import cli
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = cli.parser().parse_args([command])
    except SystemExit:
        return False
    with tempfile.TemporaryDirectory() as folder:
        try:
            cli.dispatch(args, SimpleNamespace(data_dir=str(Path(folder) / 'data'), repo=folder, root=str(ROOT)))
        except storage.DevFlowError as exc:
            return 'Unknown command' not in str(exc)
    return True


class RetroBase(unittest.TestCase):
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

    def mod(self, *argv, repo=None):
        return run_module(self.data, repo or self.repo, *argv)

    def start_run(self):
        return self.cli('_run', 'start', '--mode', 'feature', '--request', 'Retro feature', '--criterion', 'c1',
                        '--runtime', 'claude', '--owner', 'co')

    def journal(self):
        path = self.data / 'retro.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


GOOD = {'went_well': ['Small diff, quick review'],
        'problems': [{'category': 'tooling', 'text': 'Test suite took 6 minutes on 1.0.17 (2026-10-09)'}],
        'suggestions': ['Run affected tests first']}


class RetroValidationTests(RetroBase):
    def test_limits_and_shape(self):
        self.assertEqual(retro.validate(GOOD)['problems'][0]['category'], 'tooling')
        retro.validate({'went_well': ['a', 'b', 'c'], 'suggestions': ['x'] * 3,
                        'problems': [{'category': c, 'text': 'p'} for c in retro.CATEGORIES]})
        bad = [
            {'went_well': ['a'] * 4}, {'suggestions': ['a'] * 4},
            {'problems': [{'category': 'process', 'text': 'p'}] * 6},
            {'went_well': ['']}, {'went_well': ['   ']}, {'went_well': ['two\nlines']}, {'went_well': ['tab\there']},
            {'went_well': ['x' * 201]}, {'went_well': 'not a list'}, {'went_well': [3]},
            {'problems': [{'category': 'people', 'text': 'p'}]}, {'problems': [{'category': 'process'}]},
            {'problems': [{'category': 'process', 'text': 'p', 'extra': 1}]}, {'problems': ['plain text']},
            {'went_well': ['ok'], 'run_id': 'x'}, {}, {'went_well': [], 'problems': [], 'suggestions': []}, [],
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(storage.DevFlowError):
                retro.validate(value)
        retro.validate({'went_well': ['x' * 200]})

    def test_privacy_guard_rejects_personal_data(self):
        private = ['Mail juan.perez@example.com about it', 'Call 600 123 456 when done', 'Phone +34 600123456',
                   'Refund to ES91 2100 0418 4502 0005 1332', 'IBAN ES9121000418450200051332',
                   'Customer DNI 12345678Z failed', 'NIF 12345678-Z', 'NIE X1234567L blocked', 'CIF B12345678 rejected']
        for text in private:
            for value in ({'went_well': [text]}, {'suggestions': [text]},
                          {'problems': [{'category': 'process', 'text': text}]}):
                with self.subTest(text=text, value=value), self.assertRaises(storage.DevFlowError) as caught:
                    retro.validate(value)
                self.assertIn('personal data', str(caught.exception))
        # Dates, versions, SHAs and small numbers are normal process notes.
        for text in ('Release 1.0.17 on 2026-10-09 12:30:01', 'Commit ab12f3c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3',
                     'Took 1234 ms over 20-30 runs', 'Lite R001 rule was stale'):
            retro.validate({'went_well': [text]})

    def test_exactly_one_target(self):
        path = self.write('retro.json', GOOD)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--input', path)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--run', 'a', '--lite', 'b', '--owner', 'co', '--input', path)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--run', 'missing-run', '--owner', 'co', '--input', path)
        self.assertFalse((self.data / 'runs' / 'missing-run').exists())
        self.assertFalse((self.data / 'retro.jsonl').exists())


class RetroRecordTests(RetroBase):
    def test_run_retro_owner_replace_history_and_global_journal(self):
        run = self.start_run()
        path = self.write('retro.json', GOOD)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--run', run['run_id'], '--input', path)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--run', run['run_id'], '--owner', 'intruder', '--input', path)
        first = self.mod('_retro', 'add', '--run', run['run_id'], '--owner', 'co', '--input', path)
        self.assertFalse(first['replaced_previous'])
        second_input = {'problems': [{'category': 'rules', 'text': 'Rule R002 was stale'}]}
        second = self.mod('_retro', 'add', '--run', run['run_id'], '--owner', 'co',
                          '--input', self.write('retro2.json', second_input))
        self.assertTrue(second['replaced_previous'])
        stored = json.loads((self.data / 'runs' / run['run_id'] / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['retro']['problems'], second_input['problems'])
        self.assertEqual(len(stored['retro_history']), 1)
        self.assertEqual(stored['retro_history'][0]['went_well'], GOOD['went_well'])
        self.assertEqual(stored['events'][-1]['event'], 'retro recorded')
        lines = self.journal()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(set(line), {'at', 'mode', 'level', 'problems', 'suggestions', 'went_well'})
            self.assertEqual((line['mode'], line['level']), ('feature', 'full'))
        raw = (self.data / 'retro.jsonl').read_text(encoding='utf-8')
        for secret in (run['run_id'], run['branch'], self.repo.name, str(self.repo), str(self.repo).replace('\\', '\\\\'),
                       run['workspace']):
            self.assertNotIn(secret, raw)

    def test_lite_retro_owner_rules_and_levels(self):
        owned = self.cli('_lite', 'start', '--mode', 'error', '--request', 'Owned bug', '--owner', 'co')
        path = self.write('retro.json', GOOD)
        for owner in (None, 'intruder'):
            argv = ['_retro', 'add', '--lite', owned['id'], '--input', path] + (['--owner', owner] if owner else [])
            with self.subTest(owner=owner), self.assertRaises(storage.DevFlowError):
                self.mod(*argv)
        self.mod('_retro', 'add', '--lite', owned['id'], '--owner', 'co', '--input', path)
        self.mod('_retro', 'add', '--lite', owned['id'], '--owner', 'co', '--input', path)
        record = json.loads((self.data / 'lite' / (owned['id'] + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(record['retro']['went_well'], GOOD['went_well'])
        self.assertEqual(len(record['retro_history']), 1)
        other = self.make_repo('other')
        free = self.cli('_lite', 'start', '--mode', 'feature', '--request', 'Free', '--review', repo=other)
        self.mod('_retro', 'add', '--lite', free['id'], '--input', path, repo=other)
        self.assertEqual([(l['mode'], l['level']) for l in self.journal()],
                         [('error', 'lite'), ('error', 'lite'), ('feature', 'lite+review')])
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--lite', 'lite-unknown', '--input', path)
        with self.assertRaises(storage.DevFlowError):
            self.mod('_retro', 'add', '--lite', '../escape', '--input', path)


class RetroSummaryTests(RetroBase):
    def test_summary_is_read_only_without_data_dir(self):
        result = self.mod('retro')
        self.assertEqual(result['total_retros'], 0)
        self.assertIsNone(result['source'])
        self.assertEqual(result['problems_by_category'], {c: 0 for c in retro.CATEGORIES})
        self.assertFalse(self.data.exists())
        with self.assertRaises(storage.DevFlowError):
            retro.summary(self.data, since_days=0)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.mod('retro', '--category', 'people')

    def test_summary_counts_filters_and_orders_newest_first(self):
        now = dt.datetime.now(dt.timezone.utc)
        entries = [{'at': (now - dt.timedelta(days=40)).isoformat(), 'mode': 'error', 'level': 'full',
                    'problems': [{'category': 'model', 'text': 'old model problem'}],
                    'suggestions': ['old suggestion'], 'went_well': []}]
        for index in range(12):
            entries.append({'at': (now - dt.timedelta(hours=12 - index)).isoformat(), 'mode': 'feature',
                            'level': 'lite', 'problems': [{'category': 'tooling', 'text': f'tooling {index}'}] +
                            ([{'category': 'process', 'text': f'process {index}'}] if index % 2 == 0 else []),
                            'suggestions': [f'suggestion {index}'], 'went_well': ['fine']})
        self.data.mkdir()
        content = ''.join(json.dumps(e) + '\n' for e in reversed(entries)) + 'not json\n'
        (self.data / 'retro.jsonl').write_text(content, encoding='utf-8')
        everything = self.mod('retro')
        self.assertEqual(everything['total_retros'], 13)
        self.assertEqual(everything['problems_by_category'],
                         {'process': 6, 'rules': 0, 'tooling': 12, 'model': 1, 'environment': 0})
        self.assertEqual(len(everything['recent_problems']), 10)
        self.assertEqual(everything['recent_problems'][0]['text'], 'tooling 11')
        self.assertEqual([s['text'] for s in everything['recent_suggestions']][:2], ['suggestion 11', 'suggestion 10'])
        self.assertEqual(len(everything['recent_suggestions']), 10)
        self.assertEqual(everything['skipped_lines'], 1)
        recent = self.mod('retro', '--since', '30')
        self.assertEqual(recent['total_retros'], 12)
        self.assertEqual(recent['problems_by_category']['model'], 0)
        process = self.mod('retro', '--category', 'process')
        self.assertEqual(process['total_retros'], 6)
        self.assertEqual(process['problems_by_category'], {'process': 6})
        self.assertEqual({p['category'] for p in process['recent_problems']}, {'process'})
        self.assertEqual(process['recent_problems'][0]['text'], 'process 10')
        model = self.mod('retro', '--category', 'model', '--since', '30')
        self.assertEqual((model['total_retros'], model['recent_problems']), (0, []))
        self.assertEqual((self.data / 'retro.jsonl').read_text(encoding='utf-8'), content)

    def test_added_retros_feed_summary(self):
        run = self.start_run()
        self.mod('_retro', 'add', '--run', run['run_id'], '--owner', 'co', '--input', self.write('r.json', GOOD))
        result = self.mod('retro', '--category', 'tooling')
        self.assertEqual(result['total_retros'], 1)
        self.assertEqual(result['recent_suggestions'][0]['text'], 'Run affected tests first')


@unittest.skipUnless(cli_hooked('retro'), 'retro is not wired into cli.py yet (integration hook pending)')
class RetroCliTests(RetroBase):
    def test_cli_add_and_summary(self):
        run = self.start_run()
        path = self.write('retro.json', GOOD)
        self.cli('_retro', 'add', '--run', run['run_id'], '--owner', 'intruder', '--input', path, ok=False)
        stored = self.cli('_retro', 'add', '--run', run['run_id'], '--owner', 'co', '--input', path)
        self.assertEqual(stored['retro']['suggestions'], GOOD['suggestions'])
        bad = self.write('bad.json', {'went_well': ['Ping me at someone@example.com']})
        self.assertIn('personal data', self.cli('_retro', 'add', '--run', run['run_id'], '--owner', 'co',
                                               '--input', bad, ok=False))
        summary = self.cli('retro', '--since', '7', '--category', 'tooling')
        self.assertEqual(summary['total_retros'], 1)
        empty = self.root / 'empty-data'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(empty),
                                 '--repo', str(self.repo), 'retro'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['total_retros'], 0)
        self.assertFalse(empty.exists())


if __name__ == '__main__':
    unittest.main()
