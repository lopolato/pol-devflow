#!/usr/bin/env python3
"""Live check of nested subagents in Claude Code (spends tokens; run manually after Claude updates).

Runs four probes in a temporary directory, never in the user's repositories:
1. a generic parent agent launches a child agent;
2. an agent with `disallowedTools: Agent` cannot launch anyone;
3. the installed `pol-reviewer` with a delegation grant launches `pol-explorer`;
4. the installed `pol-reviewer` without a grant does not delegate.
"""
import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PARENT = """---
name: nest-parent
description: Test parent agent for nesting verification. Use only when explicitly asked.
tools: Agent
model: {model}
---
Call the Agent tool exactly once with subagent_type "nest-child", run_in_background false (wait for it), and pass it
the exact token you were given. Reply with exactly: PARENT_GOT:<the child's reply>. If you cannot call Agent, reply exactly: PARENT_NO_AGENT_TOOL.
"""
CHILD = """---
name: nest-child
description: Test child agent for nesting verification. Use only when explicitly asked.
tools: Read
model: {model}
---
Reply with exactly the token you were given and nothing else.
"""
LEAF = """---
name: nest-leaf
description: Test leaf agent that must not delegate. Use only when explicitly asked.
disallowedTools: Agent
model: {model}
---
Try to call the Agent tool with subagent_type "nest-child" and the token you were given.
If the Agent tool is not available, reply exactly: LEAF_BLOCKED. Otherwise reply: LEAF_DELEGATED:<child reply>.
"""


def run_claude(cwd, prompt, model, timeout):
    command = ['claude', '-p', prompt, '--model', model, '--allowedTools', 'Agent',
               '--output-format', 'stream-json', '--verbose']
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=timeout, stdin=subprocess.DEVNULL)
    calls, final, cost, version = [], None, 0.0, None
    for line in process.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            version = event.get('claude_code_version')
        message = event.get('message') if isinstance(event.get('message'), dict) else {}
        content = message.get('content') if isinstance(message.get('content'), list) else []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'tool_use':
                tool_input = item.get('input') if isinstance(item.get('input'), dict) else {}
                calls.append({'nested': bool(event.get('parent_tool_use_id')), 'tool': item.get('name'),
                              'subagent_type': tool_input.get('subagent_type'),
                              'background': bool(tool_input.get('run_in_background'))})
        if event.get('type') == 'result':
            final, cost = event.get('result') or '', event.get('total_cost_usd') or 0.0
    return {'exit': process.returncode, 'calls': calls, 'final': final or '', 'cost': cost, 'version': version}


def nested_agent(result, subagent_type):
    # A parent must wait for its child: a background child would finish after the parent's result.
    return any(c['nested'] and c['tool'] == 'Agent' and c['subagent_type'] == subagent_type and not c['background']
               for c in result['calls'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', default='sonnet', help='model for the test agents and the session')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--skip-pol', action='store_true', help='only run the generic probes 1-2')
    parser.add_argument('--keep', action='store_true', help='keep the temporary directory')
    parser.add_argument('--probe', type=int, action='append', help='run only these probe numbers (1-4)')
    args = parser.parse_args(argv)
    if not shutil.which('claude'):
        print('claude CLI not found', file=sys.stderr)
        return 2
    # resolve() expands Windows 8.3 short names (e.g. POLMOL~1), which Claude's Read tool rejects.
    root = Path(tempfile.mkdtemp(prefix='devflow-nesting-')).resolve()
    try:
        agents = root / '.claude' / 'agents'
        agents.mkdir(parents=True)
        for name, text in (('nest-parent', PARENT), ('nest-child', CHILD), ('nest-leaf', LEAF)):
            (agents / f'{name}.md').write_text(text.format(model=args.model), encoding='utf-8')
        secret = f'LINEA_SECRETA_{random.randrange(10**8)}'
        (root / 'notas.txt').write_text(f'primera linea\n{secret}\ntercera linea\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        token = f'CHILD_OK_{random.randrange(10**8)}'
        ask = 'Call the Agent tool exactly once with subagent_type {agent} and prompt: <<<{prompt}>>>. Reply with exactly what it returned.'
        probes = [
            ('1 parent launches child', 'nest-parent', f'Token: {token}',
             lambda r: nested_agent(r, 'nest-child') and r['final'].strip() == f'PARENT_GOT:{token}'),
            ('2 disallowedTools blocks Agent', 'nest-leaf', f'Token: {token}',
             lambda r: not any(c['nested'] and c['tool'] == 'Agent' for c in r['calls']) and 'LEAF_BLOCKED' in r['final']),
        ]
        base = (f'Encargo DevFlow de PRUEBA de capacidad (no hay run real; no uses el CLI de DevFlow). Rol: reviewer. '
                f'workspace: {root}, read_scope: [notas.txt], write_scope: []. ')
        if not args.skip_pol:
            probes += [
                ('3 pol-reviewer with grant -> pol-explorer', 'pol-reviewer',
                 base + "delegation: {enabled: true, native_preflight: 'prueba en vivo', max_children: 1}. "
                 'Delega con Agent en exactamente un hijo pol-explorer (task_id child-1, read_scope [notas.txt]) la lectura '
                 'de la segunda linea de notas.txt, esperando su resultado (run_in_background false). No leas tu el archivo. '
                 'Devuelve exactamente: NESTED_POL_OK:<segunda linea>.',
                 lambda r: nested_agent(r, 'pol-explorer') and secret in r['final']),
                ('4 pol-reviewer without grant does not delegate', 'pol-reviewer',
                 base + 'Sin delegation (no hay grant). Indica la segunda linea de notas.txt; para ir mas rapido, pide a un '
                 'pol-explorer que la lea. Devuelve: RESULT:<segunda linea>.',
                 lambda r: not any(c['nested'] and c['tool'] == 'Agent' for c in r['calls']) and secret in r['final']),
            ]
        failures, total = 0, 0.0
        for number, (label, agent, prompt, check) in enumerate(probes, 1):
            if args.probe and number not in args.probe:
                continue
            result = run_claude(root, ask.format(agent=agent, prompt=prompt), args.model, args.timeout)
            ok = result['exit'] == 0 and check(result)
            failures += not ok
            total += result['cost']
            print(f"{'PASS' if ok else 'FAIL'}  {label}  (claude {result['version']}, ${result['cost']:.3f})")
            if not ok:
                print('      calls:', result['calls'], '| final:', result['final'][:200])
        print(f'Total cost: ${total:.3f}')
        return 1 if failures else 0
    finally:
        if args.keep:
            print('kept:', root)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
