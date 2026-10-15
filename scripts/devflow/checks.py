"""Run a check (tests, lint, build) keeping its full output out of the agent context: log on disk, summary back."""
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from .storage import DevFlowError, atomic_write, digest, now

TAIL_LINES = 30
FAILURE_LINES = 20
FAILURE_LINE_CHARS = 300
DEFAULT_TIMEOUT = 1800
# Lines that usually carry the reason of a failure across runners (pytest, unittest, node, jest, tsc, eslint, go).
FAILURE = re.compile(r'(?i)(\bFAIL(ED|URE)?\b|\bERROR\b|Traceback|AssertionError|\bassert\b.*\bfailed\b|'
                     r'\bnot ok\b|✕|×|error TS\d+|\bpanic:|Exception\b)')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def check_dir(data, run_id=None, lite_id=None):
    data = Path(data)
    if run_id:
        return data / 'runs' / run_id / 'checks'
    if lite_id:
        return data / 'lite' / (lite_id + '.checks')
    return data / 'checks'


def run(data, workspace, command, name, run_id=None, lite_id=None, timeout=DEFAULT_TIMEOUT):
    if not command:
        raise DevFlowError('_check run needs the command after --')
    if not NAME.match(name or ''):
        raise DevFlowError('--name must be 1-64 letters, digits, dot, dash or underscore')
    if type(timeout) is not int or timeout <= 0:
        raise DevFlowError('--timeout needs a positive number of seconds')
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise DevFlowError('--workspace must be an existing folder')
    # Windows launchers such as npm/pnpm are .cmd files: resolve them through PATH/PATHEXT first.
    if not any(sep in command[0] for sep in ('/', '\\')):
        command = [shutil.which(command[0], path=os.environ.get('PATH')) or command[0], *command[1:]]
    started, clock = now(), time.monotonic()
    try:
        # No shell: the argv is executed as given, so quoting and pipes are never reinterpreted.
        process = subprocess.run(command, cwd=workspace, capture_output=True, timeout=timeout)
        code, out, err, status = process.returncode, process.stdout, process.stderr, None
    except subprocess.TimeoutExpired as exc:
        code, out, err, status = None, exc.stdout or b'', exc.stderr or b'', 'timeout'
    except OSError as exc:
        raise DevFlowError(f'Cannot run {command[0]}: {exc}') from exc
    duration = round(time.monotonic() - clock, 1)
    text = (out or b'').decode('utf-8', 'replace') + ('\n' if out and err else '') + (err or b'').decode('utf-8', 'replace')
    lines = text.splitlines()
    status = status or ('passed' if code == 0 else 'failed')
    header = f'# command: {command}\n# workspace: {workspace}\n# started: {started}\n# exit: {code} ({status})\n'
    content = (header + text + ('' if text.endswith('\n') or not text else '\n')).encode('utf-8')
    path = check_dir(data, run_id, lite_id) / f'{name}-{uuid.uuid4().hex[:8]}.log'
    atomic_write(path, content)
    failures = [line.strip()[:FAILURE_LINE_CHARS] for line in lines if FAILURE.search(line)] if status != 'passed' else []
    return {'name': name, 'status': status, 'exit_code': code, 'duration_s': duration, 'started_at': started,
            'log': str(path.resolve()), 'log_sha256': digest(content), 'lines': len(lines),
            'failures': failures[:FAILURE_LINES], 'failures_more': max(0, len(failures) - FAILURE_LINES),
            'tail': [line[:FAILURE_LINE_CHARS] for line in lines[-TAIL_LINES:]] if status != 'passed' else lines[-3:],
            'note': 'Full output is in log; search it (grep/Read with offset) instead of rerunning the command.'}
