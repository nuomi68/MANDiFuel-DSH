#!/usr/bin/env python3
"""软件能力表公共入口；支持批量查询和有限输入检查。"""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'lib'))
from mandifuel_prepare.capabilities import main, query, check_case

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as e:
        raise SystemExit(f'error: {e}') from e
