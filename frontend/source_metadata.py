"""Small, read-only facts from case inputs; never infer units from magnitudes."""
from functools import lru_cache
from pathlib import Path
import re


def case_time_unit(case):
    path=Path(case)/'system/controlDict'
    try:
        stat=path.stat()
        return _time_unit(str(path),stat.st_mtime_ns,stat.st_size)
    except (OSError,UnicodeError):return None


@lru_cache(maxsize=128)
def _time_unit(filename,mtime,size):
    text=Path(filename).read_text()
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    blocks=re.findall(r'\buserTime\s*\{([^{}]*)\}',text)
    if not blocks:return None if re.search(r'\buserTime\b|#include',text) else 's'
    if len(blocks)!=1:return None
    types=re.findall(r'\btype\s+(\w+)\s*;',blocks[0])
    return {'days':'d','seconds':'s'}.get(types[0]) if len(types)==1 else None
