#!/usr/bin/env python3
import sys
from devflow.cli import main

if __name__ == '__main__':
    raise SystemExit(main(['_validate', *sys.argv[1:]]))
