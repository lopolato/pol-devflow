#!/usr/bin/env python3
"""Noninteractive model configuration; optional interactive UI is deferred."""
import sys
from devflow.cli import main

if __name__ == '__main__':
    raise SystemExit(main(['config', *sys.argv[1:]]))
