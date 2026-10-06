#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from devflow.cli import main

if __name__ == '__main__':
    raise SystemExit(main(['_generate', '--runtime', 'codex', *sys.argv[1:]]))
