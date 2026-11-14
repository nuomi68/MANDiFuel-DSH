#!/usr/bin/env python3
"""Read back documented fixed-step restart controls without invoking a solver."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'skills/prepare-offbeat-case/scripts'))
from foam_edit import set_foam_entry
source=ROOT/'runs/candidate-pairs-20261113-direct-02/W01/source-case'
def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}
original=hashes(source)
with tempfile.TemporaryDirectory(prefix='mandifuel-offline-time-card-') as temporary:
    target=Path(temporary)/'case';shutil.copytree(source,target)
    changes={'startFrom':'startTime','startTime':'0','stopAt':'endTime',
             'endTime':'788400','deltaT':'78840','adjustableTimeStep':'off',
             'adjustableWriteTimeStep':'false','writeControl':'timeStep','writeInterval':'1',
             'writeFormat':'ascii','writeCompression':'off'}
    records=[set_foam_entry(target,'system/controlDict',entry,value) for entry,value in changes.items()]
    for record in records:
        assert record['value'].strip()==changes[record['entry']],record
    after=hashes(target)
    assert {k:v for k,v in after.items() if k!='system/controlDict'}=={k:v for k,v in original.items() if k!='system/controlDict'}
assert hashes(source)==original
print(json.dumps({'fixed_step_time_card_readbacks':len(records),'unrelated_inputs_unchanged':True,
                  'source_unchanged':True,'solver_starts':0},ensure_ascii=False))
