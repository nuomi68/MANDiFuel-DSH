#!/usr/bin/env python3
"""冻结原版球壳输入和原生记录工具，不含任务解法或软件实现修改。"""
from pathlib import Path
import hashlib
import json
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

REPO=Path(__file__).resolve().parents[2]
root=REPO/'runs/quality-reference-20261114-01';root.mkdir(exist_ok=False)
work=root/'workspace';work.mkdir();case=work/'hollowsphere-original';case.mkdir()
source=Path('/home/lwz/offbeat/Cases/Verification/trisoModulesTest/hollowsphere_1D')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for name in ('0','constant','system'):shutil.copytree(source/name,case/name,symlinks=False)
inputs={str(p.relative_to(case)):sha(p) for p in case.rglob('*') if p.is_file()}
assert all(sha(source/name)==digest for name,digest in inputs.items())
recipe='#!/usr/bin/env bash\nset -euo pipefail\nblockMesh > log.blockMesh 2>&1\n'
if (case/'system/changeDictionaryDict').exists():recipe+='changeDictionary > log.changeDictionary 2>&1\n'
recipe+='offbeat > log.offbeat 2>&1\n';(case/'Allrun.compute').write_text(recipe)
bin=root/'instrumented-bin';bin.mkdir()
shutil.copyfile(REPO/'runs/rag-modeling-pairs-20261114-03/definition/solver-wrapper.py',bin/'offbeat');(bin/'offbeat').chmod(0o755)
(bin/'config.json').write_text(json.dumps({'workspace':str(work),'solver_start_cap':None,'real_binary':'/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat'},indent=2)+'\n')
manifest={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'purpose':'用户要求对原版基准答案作数值复核；独立于此前DSH对照，不加入六会话成本。','original_source':str(source),'case':str(case),'input_hashes':inputs,'original_Allrun_sha256':sha(source/'Allrun'),'compute_recipe':'仅原始预处理和求解，原始比较脚本常量另行读取；未改0/constant/system。','reused_original_Cs_event':'runs/rag-modeling-pairs-20261114-03/M01/bare/workspace/execution-evidence/75c91a42e66b41b2bc0af14ae1a721a1','model_requests':0}
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(root)
