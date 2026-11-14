#!/usr/bin/env python3
"""Public case execution interface; implementation is bundled at the plugin root."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'lib'))
from mandifuel_run.case import inspect_case, main, run_case  # noqa: E402, F401

if __name__ == '__main__':
    raise SystemExit(main())
