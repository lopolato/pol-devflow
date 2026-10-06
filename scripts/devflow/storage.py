"""Validated data paths, atomic writes, locks and recoverable transactions."""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path


class DevFlowError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def package_root():
    return Path(__file__).resolve().parents[2]


def data_home():
    override = os.environ.get('DEVFLOW_DATA_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'PolDevFlow'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'pol-devflow'


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DevFlowError(f'Duplicate key: {key}')
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique_pairs)
    except (OSError, ValueError) as exc:
        raise DevFlowError(f'Cannot read JSON {path}: {exc}') from exc


def digest(content):
    return hashlib.sha256(content).hexdigest()


def reject_symlink(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise DevFlowError(f'Refusing symlink/junction destination: {item}')


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', value):
        raise DevFlowError('Invalid identifier; use letters, numbers, underscore or hyphen')
    return value


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise DevFlowError(f'Path escapes expected root: {path}')
    return path


def _replace(source, target, attempts=6):
    # Windows antivirus/indexers can hold the target for a moment (WinError 5/32); retry briefly.
    for attempt in range(attempts):
        try:
            return os.replace(source, target)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * 2 ** attempt)


def atomic_write(path, content):
    path = Path(path)
    reject_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.devflow-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class FileLock:
    def __init__(self, path, owner):
        self.path, self.owner = Path(path), owner
        self.token = uuid.uuid4().hex

    def __enter__(self):
        reject_symlink(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open('x', encoding='utf-8') as handle:
                json.dump({'owner': self.owner, 'token': self.token, 'pid': os.getpid(), 'created_at': now()}, handle)
        except FileExistsError as exc:
            raise DevFlowError(f'Another operation owns lock {self.path}; inspect it before recovering a stale lock') from exc
        return self

    def __exit__(self, *args):
        if self.path.exists() and read_json(self.path).get('token') == self.token:
            self.path.unlink()


def transaction(changes, backup_root):
    """All conflicts are checked by caller before entry; failures restore prior bytes."""
    normalized = {Path(p): content for p, content in changes.items()}
    before = {}
    for path in normalized:
        reject_symlink(path)
        if path.exists() and not path.is_file():
            raise DevFlowError(f'Destination is not a file: {path}')
        before[path] = path.read_bytes() if path.exists() else None
    backup = Path(backup_root) / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    record = {str(p.absolute()): None if b is None else base64.b64encode(b).decode('ascii') for p, b in before.items()}
    atomic_write(backup / 'before.json', json_bytes(record))
    written = []
    try:
        for path, content in normalized.items():
            # Detect edits between initial snapshot and a later write in the batch.
            current = path.read_bytes() if path.exists() else None
            if current != before[path]:
                raise DevFlowError(f'Destination changed during transaction: {path}')
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                atomic_write(path, content)
            written.append(path)
    except Exception as exc:
        failures = []
        for path in reversed(written):
            try:
                if before[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, before[path])
            except Exception as rollback_exc:
                failures.append(f'{path}: {rollback_exc}')
        detail = '; rollback incomplete: ' + '; '.join(failures) if failures else '; previous files restored'
        raise DevFlowError(f'Transaction failed: {exc}{detail}. Backup: {backup}') from exc
    return str(backup)
