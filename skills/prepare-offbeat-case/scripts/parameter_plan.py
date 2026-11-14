#!/usr/bin/env python3
"""公共参数计划入口；使用说明见 references/parameter-plan.md。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'lib'))
from mandifuel_prepare.parameter_plan import main

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'error: {exc}') from exc
