"""Small, read-only facts from case inputs; never infer units from magnitudes."""
from functools import lru_cache
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from mandifuel_verify.inputs import Unavailable,dictionary,word


def case_time_unit(case):
    path=Path(case)/'system/controlDict'
    try:
        stat=path.stat()
        return _time_unit(str(path),(stat.st_dev,stat.st_ino,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size))
    except (OSError,UnicodeError):return None


@lru_cache(maxsize=128)
def _time_unit(filename,identity):
    try:
        control=dictionary(Path(filename).read_text())
        # A directive in functions cannot supply a top-level userTime entry.
        # Top-level includes/macros remain unresolved; never execute them or
        # guess a unit from numeric time values.
        if control.get('_directives'):return None
        if 'userTime' not in control:return 's'
        return {'days':'d','seconds':'s'}.get(word(control,'userTime','type'))
    except Unavailable:return None
