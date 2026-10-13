"""Command examples in the markdown must exist in the real CLI parser (subcommand, action and flags)."""
import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from devflow import cli

COMMANDS = ('help', 'status', 'stats', 'config', 'cleanup', 'retro', 'rules', 'error', 'feature', 'optimize',
            '_run', '_lite', '_git', '_metrics', '_profile', '_rules', '_retro', '_orca', '_workspace', '_validate',
            '_capabilities', '_install', '_uninstall')
# Global options of scripts/devflow.py, accepted before or after the subcommand.
CONTEXT_FLAGS = ('--data-dir', '--repo', '--root')
PREFIX = re.compile(r'^(?:\$\s+)?(?:python3?\s+"?[^\s"]*devflow\.py"?|/pol-devflow|\$pol-devflow)(?=\s|$)')
FLAG = re.compile(r'(?<![\w-])(--[a-z][a-z0-9-]*)')
PLACEHOLDER = re.compile(r'^(?:[A-Z][A-Z0-9_]*|\.\.\.|…)?$')

# Temporary allowlist of documented tokens that the parser does not accept: (file, command, token).
# The integrator fixes the markdown and empties it; stale entries fail test_known_gaps_are_still_real.
KNOWN_DOC_GAPS = set()


def doc_files(root=ROOT):
    root = Path(root)
    files = [root / name for name in ('SKILL.md', 'README.md', 'PILOTO.md')]
    files += sorted((root / 'core').rglob('*.md')) + sorted((root / 'adapters').glob('*/README.md'))
    return [path for path in files if path.is_file()]


def code_spans(text):
    """(line number, code) for inline code spans and for each line of fenced blocks."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith('```'):
            fenced = not fenced
            continue
        if fenced:
            if line.strip():
                yield number, line.strip()
            continue
        for match in re.finditer(r'(?<!`)`([^`\n]+)`(?!`)', line):
            yield number, match.group(1).strip()


def subcommands(parser):
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    result = {}
    for name, sub in action.choices.items():
        options = {}
        for item in sub._actions:
            for option in item.option_strings:
                options[option] = item
        positional = next((a for a in sub._actions if not a.option_strings and a.dest == 'action' and a.choices),
                          None)
        result[name] = {'options': options, 'actions': tuple(positional.choices) if positional else None}
    return result


def words(value):
    """Alternatives of a token such as [show|validate] or codex|claude], without placeholders."""
    return [w for w in value.strip('[]()').split('|') if not PLACEHOLDER.fullmatch(w.strip('[]()'))]


def check_span(code, commands):
    """List of (command, token, reason) problems of one code span; [] when it is not a command example."""
    match = PREFIX.match(code)
    rest = code[match.end():] if match else code
    tokens = re.sub(r'<[^>]*>', ' ', rest).split()
    while tokens and tokens[0].split('=')[0] in CONTEXT_FLAGS:
        tokens = tokens[1:] if '=' in tokens[0] else tokens[2:]
    if not tokens:
        return []
    names = tokens[0].split('|')
    if not match and not all(name in COMMANDS for name in names):
        return []
    problems = []
    for name in names:
        if name not in commands:
            problems.append((name, name, 'unknown subcommand'))
            continue
        spec = commands[name]
        if spec['actions'] and len(tokens) > 1 and not tokens[1].startswith('-'):
            for word in words(tokens[1]):
                if word not in spec['actions']:
                    problems.append((name, word, 'unknown action'))
        for index, token in enumerate(tokens[1:], 1):
            for flag in FLAG.findall(token):
                if flag in CONTEXT_FLAGS or flag == '--help':
                    continue
                option = spec['options'].get(flag)
                if option is None:
                    problems.append((name, flag, 'unknown flag'))
                    continue
                value = tokens[index + 1] if index + 1 < len(tokens) and '=' not in token else None
                if option.choices and value and not value.lstrip('[').startswith('-'):
                    for word in words(value):
                        if word not in option.choices:
                            problems.append((name, f'{flag} {word}', 'invalid choice'))
    return problems


def scan(root=ROOT, files=None):
    commands = subcommands(cli.parser())
    found = []
    for path in files or doc_files(root):
        relative = path.relative_to(root).as_posix()
        for number, code in code_spans(path.read_text(encoding='utf-8')):
            for command, token, reason in check_span(code, commands):
                found.append((relative, number, command, token, reason))
    return found


class DocsConsistencyTests(unittest.TestCase):
    def test_documented_commands_exist_in_the_cli(self):
        found = scan()
        unexpected = [f'{file}:{line}: {token} ({reason} for {command})'
                      for file, line, command, token, reason in found
                      if (file, command, token) not in KNOWN_DOC_GAPS]
        self.assertEqual(unexpected, [], 'Markdown mentions commands/actions/flags the CLI does not accept:\n'
                         + '\n'.join(unexpected))

    def test_known_gaps_are_still_real(self):
        current = {(file, command, token) for file, _, command, token, _ in scan()}
        self.assertEqual(sorted(KNOWN_DOC_GAPS - current), [], 'Remove fixed entries from KNOWN_DOC_GAPS')

    def test_scans_the_expected_documents(self):
        names = {path.relative_to(ROOT).as_posix() for path in doc_files()}
        self.assertTrue({'SKILL.md', 'README.md', 'core/coordinator.md', 'adapters/orca/README.md'} <= names)
        # Guard against a parser/regex change that silently stops recognising examples.
        examples = [code for path in doc_files() for _, code in code_spans(path.read_text(encoding='utf-8'))
                    if check_span(code, {})]
        self.assertGreater(len(examples), 50)


class CheckerTests(unittest.TestCase):
    """The checker itself: detects real mismatches and ignores placeholders and prose."""

    def setUp(self):
        self.commands = subcommands(cli.parser())

    def problems(self, code):
        return [(token, reason) for _, token, reason in check_span(code, self.commands)]

    def test_valid_examples_pass(self):
        for code in ('_run start --mode feature --request DESCRIPTION --criterion C --runtime codex|claude --owner S',
                     'python scripts/devflow.py --repo PROJECT _lite start --mode error|feature [--review]',
                     'python "<skill>/scripts/devflow.py" _git commit --workspace REPO --path FILE',
                     '/pol-devflow error --lite <bug real pequeño>', '$pol-devflow config set --runtime codex --inherit',
                     'config [show|validate|set ...]', '_lite link|settle|account --lite ID', '_orca settle ... --input J',
                     'error|feature [--lite|--full] [--review] [--plan-only]', 'cleanup --apply --purge-history',
                     '_metrics add --activity implementation|tests --source runtime', 'status', 'help [tema]'):
            with self.subTest(code=code):
                self.assertEqual(self.problems(code), [])

    def test_mismatches_are_reported(self):
        self.assertEqual(self.problems('_run strat --run ID'), [('strat', 'unknown action')])
        self.assertEqual(self.problems('_lite start --no-such-flag X'), [('--no-such-flag', 'unknown flag')])
        self.assertEqual(self.problems('config [show|reset]'), [('reset', 'unknown action')])
        self.assertEqual(self.problems('_capabilities --runtime gemini'), [('--runtime gemini', 'invalid choice')])
        self.assertEqual(self.problems('python scripts/devflow.py _nope --x'), [('_nope', 'unknown subcommand')])
        self.assertEqual(self.problems('error|feature --verbose'),
                         [('--verbose', 'unknown flag'), ('--verbose', 'unknown flag')])
        self.assertEqual(self.problems('stats --apply'), [('--apply', 'unknown flag')])

    def test_prose_and_other_tools_are_ignored(self):
        for code in ('git status', 'status: done | partial', 'stats.activities', 'validation[].status',
                     'terminal read/send --help', 'orca_run_id', '--features'):
            with self.subTest(code=code):
                self.assertEqual(self.problems(code), [])

    def test_spans_include_fenced_lines_and_report_line_numbers(self):
        text = 'Intro `_run strat`\n```bash\n$pol-devflow cleanup --bogus\n```\n`not code` y `_lite status --lite ID`\n'
        spans = list(code_spans(text))
        self.assertEqual(spans, [(1, '_run strat'), (3, '$pol-devflow cleanup --bogus'), (5, 'not code'),
                                 (5, '_lite status --lite ID')])


if __name__ == '__main__':
    unittest.main()
