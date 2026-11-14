#!/usr/bin/env python3
"""Exercise documented dictionary interfaces and retained results, without a solve."""
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

root=Path(__file__).resolve().parents[2]
assert os.environ['MANDIFUEL_ENVIRONMENT_READY']=='1'
assert os.environ['MANDIFUEL_TASK_PYTHON']
assert os.environ['MANDIFUEL_OFFBEAT_EXECUTABLE']
sys.path.insert(0,str(root/'skills/prepare-offbeat-case/scripts'))
from foam_edit import get_foam_entry,set_foam_entry
from importlib.util import spec_from_file_location,module_from_spec
spec=spec_from_file_location('public_case',root/'skills/execute-offbeat-case/scripts/case_runner.py');runner=module_from_spec(spec);spec.loader.exec_module(runner)
original=root/'runs/candidate-pairs-20261112-04/C04/skill/workspace/clad-oxide-17735.41d'
receipt_before=(original/'.mandifuel-execution.json').read_bytes()
with tempfile.TemporaryDirectory(prefix='mandifuel-public-contract-') as temporary:
    target=Path(temporary)/'case';(target/'system').mkdir(parents=True)
    shutil.copy2(original/'system/controlDict',target/'system/controlDict')
    edits=[set_foam_entry(target,'system/controlDict','endTime','17735.41'),
           set_foam_entry(target,'system/controlDict','deltaT','17.73541')]
    assert all(set(e)=={'file','entry','value'} for e in edits)
    assert abs(Decimal(edits[0]['value'])-Decimal('17735.41'))<Decimal('1e-10')
status=runner.inspect_case(original)
assert status['status']=='completed' and status['completion_reconciled']
final=status['final_time'];field=final+'/oxideThickness'
dimensions=get_foam_entry(original,field,'dimensions')
assert dimensions.replace('[','').replace(']','').split()==['0','1','0','0','0','0','0']
value=get_foam_entry(original,field,'boundaryField/cladOuter/value').split()
assert value[0]=='uniform' and Decimal(value[1])>0
assert (original/'.mandifuel-execution.json').read_bytes()==receipt_before
print(json.dumps({'public_edit_readback':'passed','retained_completion':'completed','actual_directory':final,'surface_boundary_entry':'passed','original_receipt_unchanged':True,'solver_starts':0},ensure_ascii=False))
