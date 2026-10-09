import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
from devflow import gitops, profile, rules, storage
from test_retro import cli_hooked, run_module


def entry(text, paths, kind='requirement', **extra):
    return {'kind': kind, 'text': text, 'paths': paths, **extra}


class RulesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for args in (('init', '-b', 'main'), ('config', 'user.name', 'DevFlow Test'),
                     ('config', 'user.email', 'devflow@example.invalid')):
            self.git(*args)
        for name in ('src/app.py', 'src/lib/util.py', 'src/lib/other.py', 'docs/guide.md', 'srcx/x.py'):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(name + '\n')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.head = self.git('rev-parse', 'HEAD')
        self.count = 0

    def git(self, *args, repo=None):
        return subprocess.run(['git', *args], cwd=repo or self.repo, check=True, capture_output=True,
                              text=True).stdout.strip()

    def write(self, value):
        self.count += 1
        path = self.root / f'input-{self.count}.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def mod(self, *argv, repo=None):
        return run_module(self.data, repo or self.repo, *argv)

    def add(self, *entries, repo_file=False, repo=None):
        return self.mod('_rules', 'add', '--input', self.write(list(entries)),
                        *(['--repo-file'] if repo_file else []), repo=repo)

    def commit_change(self, name, text='changed\n'):
        (self.repo / name).write_text(text)
        self.git('add', name)
        self.git('commit', '-m', 'change ' + name)


class RulesRegistryTests(RulesBase):
    def test_add_confirm_remove_list_and_id_assignment(self):
        first = self.add(entry('Never log tokens', ['src/app.py'], 'must_not', test='src/app.py::test_no_log',
                               source={'type': 'bug', 'ref': 'lite-abc123'}),
                         entry('Use utc timestamps', ['src/lib/'], 'convention'))
        self.assertEqual(first['source'], 'local')
        added = first['added']
        self.assertEqual([r['id'] for r in added], ['R001', 'R002'])
        self.assertEqual(added[0]['status'], 'inferred')
        self.assertEqual(added[0]['revision'], self.head)
        self.assertEqual(added[0]['source'], {'type': 'bug', 'ref': 'lite-abc123'})
        self.assertEqual(added[1]['paths'], ['src/lib'])
        self.assertEqual(added[1]['source'], {'type': 'manual'})
        for field in ('created_at', 'updated_at'):
            self.assertIn(field, added[0])
        duplicate = self.add(entry('Never log tokens', ['src/app.py'], 'must_not'))
        self.assertEqual((duplicate['added'], duplicate['skipped_duplicates']), ([], ['Never log tokens']))
        self.mod('_rules', 'remove', '--id', 'R002')
        third = self.add(entry('Docs in Spanish', ['docs'], 'convention'))
        self.assertEqual(third['added'][0]['id'], 'R003')  # Removed ids are never reused.
        self.commit_change('docs/guide.md')
        confirmed = self.mod('_rules', 'confirm', '--id', 'R001')['rule']
        self.assertEqual((confirmed['status'], confirmed['revision']), ('confirmed', self.git('rev-parse', 'HEAD')))
        explicit = self.mod('_rules', 'confirm', '--id', 'R003', '--revision', self.head[:12])['rule']
        self.assertEqual(explicit['revision'], self.head)
        for argv in (('_rules', 'confirm', '--id', 'R999'), ('_rules', 'confirm', '--id', 'X1'),
                     ('_rules', 'confirm', '--id', 'R001', '--revision', 'deadbeefdeadbeef'),
                     ('_rules', 'confirm', '--id', 'R001', '--revision', 'HEAD~1;rm'), ('_rules', 'remove', '--id', 'R002'),
                     ('_rules', 'list', '--repo-file'), ('_rules', 'for'), ('_rules', 'add'),
                     ('_rules', 'list', '--id', 'R001'), ('_rules', 'import-tests', '--limit', '0')):
            with self.subTest(argv=argv), self.assertRaises(storage.DevFlowError):
                self.mod(*argv)
        listed = self.mod('_rules', 'list')
        self.assertEqual([r['id'] for r in listed['rules']], ['R001', 'R003'])
        self.assertEqual([r['id'] for r in self.mod('_rules', 'list', '--status', 'inferred')['rules']], [])
        self.assertEqual(len(self.mod('rules', '--status', 'confirmed')['rules']), 2)

    def test_entry_validation_and_privacy_write_nothing(self):
        good = entry('Keep API stable', ['src/app.py'])
        bad = [
            entry('x', ['src/app.py'], 'should'), entry('', ['src/app.py']), entry('two\nlines', ['src/app.py']),
            entry('x' * 241, ['src/app.py']), entry('x', []), entry('x', 'src/app.py'),
            entry('x', ['src/app.py'], id='R001'), entry('x', ['src/app.py'], created_at='now'),
            entry('x', ['src/app.py'], test='src/app.py'), entry('x', ['src/app.py'], test='../a.py::t'),
            entry('x', ['src/app.py'], source={'type': 'rumor'}), entry('x', ['src/app.py'], source={'type': 'bug', 'ref': 'a b'}),
            entry('x', ['src/app.py'], status='approved'), entry('x', ['src/app.py'], revision='nothex'),
            entry('Email ana@example.com on failure', ['src/app.py']), entry('Call 600 123 456', ['src/app.py']),
            entry('Pay ES91 2100 0418 4502 0005 1332', ['src/app.py']), entry('DNI 12345678Z is a fixture', ['src/app.py']),
            entry('CIF B12345678 too', ['src/app.py']),
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(storage.DevFlowError):
                self.add(good, value)
        for value in ([], {'kind': 'requirement'}):
            with self.subTest(value=value), self.assertRaises(storage.DevFlowError):
                self.mod('_rules', 'add', '--input', self.write(value))
        self.assertFalse(rules.local_path(self.data, self.repo).exists())
        self.assertEqual(self.mod('_rules', 'list')['rules'], [])
        self.assertEqual(self.add(good)['added'][0]['id'], 'R001')

    def test_paths_must_stay_inside_repository(self):
        for path in ('../outside.py', 'src/../../outside.py', '/etc/passwd', 'C:/Windows/x', 'C:\\Windows\\x',
                     '.', '', '..'):
            with self.subTest(path=path), self.assertRaises(storage.DevFlowError):
                self.add(entry('Escapes', [path]))
            with self.subTest(path=path), self.assertRaises(storage.DevFlowError):
                self.mod('_rules', 'for', '--path', path)
        self.assertFalse(rules.local_path(self.data, self.repo).exists())
        stored = self.add(entry('Windows separators', ['src\\lib\\util.py', './docs/']))['added'][0]
        self.assertEqual(stored['paths'], ['src/lib/util.py', 'docs'])

    def test_external_storage_shared_by_linked_worktree(self):
        self.add(entry('Shared rule', ['src/app.py']))
        path = rules.local_path(self.data, self.repo)
        self.assertEqual(path.parent, self.data / 'projects')
        self.assertTrue(path.name.endswith('.rules.json'))
        self.assertEqual(path.name.removesuffix('.rules.json'), profile.local_path(self.data, self.repo).stem)
        self.assertTrue(path.is_file())
        self.assertFalse((self.repo / '.devflow').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')
        linked = self.root / 'linked'
        self.git('worktree', 'add', '-b', 'other', str(linked))
        listed = self.mod('_rules', 'list', repo=linked)
        self.assertEqual(listed['source'], 'local')
        self.assertEqual([r['text'] for r in listed['rules']], ['Shared rule'])
        self.assertEqual(self.add(entry('From worktree', ['docs']), repo=linked)['added'][0]['id'], 'R002')
        self.assertEqual(len(self.mod('_rules', 'list')['rules']), 2)
        stored = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(stored['git_common_dir'], gitops.common_dir(self.repo))
        self.assertEqual(gitops.common_dir(linked), gitops.common_dir(self.repo))

    def test_repo_file_has_priority(self):
        self.add(entry('Local rule', ['src/app.py']))
        result = self.add(entry('Versioned rule', ['docs']), repo_file=True)
        self.assertEqual(result['source'], 'repository')
        repo_file = self.repo / '.devflow' / 'rules.json'
        self.assertTrue(repo_file.is_file())
        self.assertIn('committed explicitly', result['note'])
        self.assertFalse((self.repo / '.devflow' / 'rules.lock').exists())
        listed = self.mod('_rules', 'list')
        self.assertEqual(listed['source'], 'repository')
        self.assertEqual([r['text'] for r in listed['rules']], ['Versioned rule'])
        self.assertEqual(listed['ignored_local_rules'], str(rules.local_path(self.data, self.repo)))
        self.assertIn('never instructions', listed['trust'])
        with self.assertRaises(storage.DevFlowError) as caught:
            self.add(entry('Ambiguous target', ['docs']))
        self.assertIn('--repo-file', str(caught.exception))
        with self.assertRaises(storage.DevFlowError):
            self.mod('_rules', 'remove', '--id', 'R001')
        self.mod('_rules', 'confirm', '--id', 'R001', '--repo-file')
        self.assertEqual(json.loads(repo_file.read_text(encoding='utf-8'))['rules'][0]['status'], 'confirmed')


class RulesLookupTests(RulesBase):
    def setUp(self):
        super().setUp()
        self.add(entry('App file rule', ['src/app.py']), entry('Lib dir rule', ['src/lib'], 'must_not'),
                 entry('Docs rule', ['docs'], 'convention'))

    def ids(self, *paths, command='_rules'):
        argv = [command] + (['for'] if command == '_rules' else [])
        for path in paths:
            argv += ['--path', path]
        return [r['id'] for r in self.mod(*argv)['rules']]

    def test_matching_file_and_directory_prefix_both_ways(self):
        self.assertEqual(self.ids('src/app.py'), ['R001'])
        self.assertEqual(self.ids('src/lib/util.py'), ['R002'])
        self.assertEqual(self.ids('src'), ['R002', 'R001'])  # must_not first
        self.assertEqual(self.ids('src/'), ['R002', 'R001'])
        self.assertEqual(self.ids('srcx/x.py'), [])
        self.assertEqual(self.ids('src/app.pyc'), [])
        self.assertEqual(self.ids('src\\lib\\other.py', 'docs/guide.md'), ['R002', 'R003'])
        self.assertEqual(self.ids('docs/guide.md', command='rules'), ['R003'])
        self.assertEqual([r['id'] for r in self.mod('rules')['rules']], ['R001', 'R002', 'R003'])
        result = self.mod('_rules', 'for', '--path', 'src')
        self.assertEqual((result['matched'], result['truncated']), (2, False))
        self.assertFalse(any(r['stale'] for r in result['rules']))

    def test_stale_after_commit_uncommitted_change_and_unknown_revision(self):
        self.commit_change('src/lib/util.py')
        rules_by_id = {r['id']: r for r in self.mod('_rules', 'for', '--path', 'src')['rules']}
        self.assertTrue(rules_by_id['R002']['stale'])
        self.assertEqual(rules_by_id['R002']['changed_paths'], ['src/lib/util.py'])
        self.assertFalse(rules_by_id['R001']['stale'])
        (self.repo / 'src/app.py').write_text('uncommitted\n')
        self.assertTrue(self.mod('_rules', 'for', '--path', 'src/app.py')['rules'][0]['stale'])
        self.git('checkout', '--', 'src/app.py')
        self.assertFalse(self.mod('_rules', 'for', '--path', 'src/app.py')['rules'][0]['stale'])
        (self.repo / 'docs/new.md').write_text('untracked\n')
        self.assertEqual(self.mod('_rules', 'for', '--path', 'docs')['rules'][0]['changed_paths'], ['docs/new.md'])
        (self.repo / 'docs/new.md').unlink()
        self.mod('_rules', 'confirm', '--id', 'R002')
        self.assertFalse(self.mod('_rules', 'for', '--path', 'src/lib')['rules'][0]['stale'])
        path = rules.local_path(self.data, self.repo)
        stored = json.loads(path.read_text(encoding='utf-8'))
        stored['rules'][0]['revision'] = 'deadbeef' * 5
        stored['rules'][2].pop('revision')
        path.write_text(json.dumps(stored), encoding='utf-8')
        for rule_path in ('src/app.py', 'docs'):
            item = self.mod('_rules', 'for', '--path', rule_path)['rules'][0]
            self.assertEqual((item['stale'], item['stale_reason']), (True, 'unknown revision'))

    def test_lookup_truncates_at_twenty_with_must_not_first(self):
        self.add(*[entry(f'Requirement {i}', ['src/lib/util.py']) for i in range(22)],
                 *[entry(f'Forbidden {i}', ['src/lib'], 'must_not') for i in range(3)])
        before = rules.local_path(self.data, self.repo).read_bytes()
        result = self.mod('_rules', 'for', '--path', 'src/lib/util.py')
        self.assertEqual(len(result['rules']), 20)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['matched'], 26)
        self.assertEqual([r['kind'] for r in result['rules'][:4]], ['must_not'] * 4)
        self.assertEqual(result['rules'][0]['id'], 'R002')
        self.assertEqual(rules.local_path(self.data, self.repo).read_bytes(), before)

    def test_lookup_without_registry_is_read_only(self):
        fresh = self.root / 'fresh-data'
        result = run_module(fresh, self.repo, '_rules', 'for', '--path', 'src/app.py')
        self.assertEqual((result['rules'], result['source']), ([], None))
        self.assertEqual(run_module(fresh, self.repo, 'rules')['rules'], [])
        self.assertFalse(fresh.exists())


class RulesImportTests(RulesBase):
    def test_import_tests_candidates_from_python_and_js_never_writes(self):
        files = {
            'tests/test_widget.py': ('import unittest\n\nclass WidgetTests(unittest.TestCase):\n'
                                     '    def test_rejects_empty_input(self):\n        pass\n\n'
                                     '    def test_does_not_crash_without_config(self):\n        pass\n\n'
                                     '    def helper_test_x(self):\n        pass\n\n'
                                     'async def test_single_user_login():\n    pass\n'),
            'pkg/thing_test.py': 'def test_nunca_borra_datos():\n    pass\n',
            'web/button.test.js': ("describe('Button', () => {\n  it('renders the label', () => {});\n"
                                   "  test(\"never sends twice\", () => {});\n  it.skip(`works sin red`, () => {});\n"
                                   "  it('calls 600 123 456', () => {});\n});\n"),
            'web/form.spec.ts': "it('submits without token', async () => {})\n",
            'tests/fixtures/data.json': '{"def test_fake(": 1}\n',
            'src/notatest.py': 'def test_fake():\n    pass\n',
        }
        for name, content in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(content, encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'tests')
        (self.repo / 'tests/test_untracked.py').write_text('def test_untracked():\n    pass\n')
        result = self.mod('_rules', 'import-tests')
        found = {c['test']: c for c in result['candidates']}
        expected = {
            'pkg/thing_test.py::test_nunca_borra_datos': 'must_not',
            'tests/test_widget.py::test_rejects_empty_input': 'requirement',
            'tests/test_widget.py::test_does_not_crash_without_config': 'must_not',
            'tests/test_widget.py::test_single_user_login': 'requirement',
            'web/button.test.js::Button': 'requirement',
            'web/button.test.js::renders the label': 'requirement',
            'web/button.test.js::never sends twice': 'must_not',
            'web/button.test.js::works sin red': 'must_not',
            'web/form.spec.ts::submits without token': 'must_not',
        }
        self.assertEqual({k: v['kind'] for k, v in found.items()}, expected)
        self.assertEqual(result['skipped_private'], 1)
        sample = found['tests/test_widget.py::test_rejects_empty_input']
        self.assertEqual(sample, {'kind': 'requirement', 'text': 'Rejects empty input', 'paths': ['tests/test_widget.py'],
                                  'test': 'tests/test_widget.py::test_rejects_empty_input',
                                  'source': {'type': 'import'}, 'status': 'inferred'})
        self.assertEqual(found['web/button.test.js::never sends twice']['text'], 'never sends twice')
        self.assertFalse(result['state_changed'])
        self.assertFalse(self.data.exists())
        self.assertEqual(self.git('status', '--porcelain'), '?? tests/test_untracked.py')
        limited = self.mod('_rules', 'import-tests', '--limit', '2')
        self.assertEqual((limited['count'], limited['truncated']), (2, True))
        # Candidates are valid add input once the user accepts them; registered tests are not proposed again.
        accepted = self.add(sample)['added'][0]
        self.assertEqual(accepted['source'], {'type': 'import'})
        again = self.mod('_rules', 'import-tests')
        self.assertEqual(again['already_registered'], 1)
        self.assertNotIn(sample['test'], {c['test'] for c in again['candidates']})


@unittest.skipUnless(cli_hooked('rules'), 'rules is not wired into cli.py yet (integration hook pending)')
class RulesCliTests(RulesBase):
    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/devflow.py'), '--data-dir', str(self.data),
                                 '--repo', str(self.repo), *args], capture_output=True, text=True, encoding='utf-8')
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def test_cli_add_for_and_public_alias(self):
        added = self.cli('_rules', 'add', '--input', self.write([entry('No secrets', ['src'], 'must_not')]))
        self.assertEqual(added['added'][0]['id'], 'R001')
        self.cli('_rules', 'add', '--input', self.write([entry('Escape', ['../x'])]), ok=False)
        self.assertEqual([r['id'] for r in self.cli('rules', '--path', 'src/app.py')['rules']], ['R001'])
        self.assertEqual(len(self.cli('rules')['rules']), 1)
        self.cli('_rules', 'confirm', '--id', 'R001')
        self.assertEqual(self.cli('_rules', 'list', '--status', 'confirmed')['count'], 1)
        self.assertIn('candidates', self.cli('_rules', 'import-tests'))


if __name__ == '__main__':
    unittest.main()
