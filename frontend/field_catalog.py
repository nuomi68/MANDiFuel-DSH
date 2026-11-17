"""Bounded header facts for saved fields; selection remains the presenter's job."""
from functools import lru_cache
from pathlib import Path
import re


@lru_cache(maxsize=512)
def _header(filename, mtime, size):
    from export_case import foam, field_unit
    with Path(filename).open(encoding='ascii') as stream:
        prefix=stream.read(65536)
    prefix=re.split(r'\binternalField\b',prefix,maxsplit=1)[0]
    tokens=foam._ascii_tokens(prefix,filename)
    cls,name=foam._parse_header(tokens,filename);kind=foam._class_kind(cls)
    dimensions=foam._parse_dimensions(tokens,filename)
    components=list(foam.component_names(kind))
    selectors=[name if c=='value' else name+':'+c for c in components]
    if kind=='vector':selectors.append(name+':mag')
    if kind=='symmTensor':
        selectors.append(name+':principal_max')
        if tuple(dimensions)==(1,-1,-2,0,0,0,0):selectors.append(name+':von_mises')
    if name!=Path(filename).name:raise ValueError('字段对象名与文件名不一致')
    return {'name':name,'kind':kind,'components':components,'unit':field_unit(None,dimensions),'selectors':selectors}


def saved_field_catalog(case,time,names):
    fields=[];errors=[]
    for name in names[:64]:
        path=Path(case)/time/name
        try:
            stamp=path.stat();fields.append(_header(str(path),stamp.st_mtime_ns,stamp.st_size))
        except (ValueError,OSError,UnicodeError) as error:errors.append({'name':name,'error':str(error)[:240]})
    return {'time':time,'fields':fields,'errors':errors[:8]}
