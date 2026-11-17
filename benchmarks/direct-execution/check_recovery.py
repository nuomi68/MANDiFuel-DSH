#!/usr/bin/env python3
"""真实子进程测试恢复凭据和无限记账；仅用假求解器，不启动OFFBEAT。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'lib'));sys.path.insert(0,str(ROOT/'benchmarks/candidate-pairs'))
from mandifuel_run.case import run_case, failure_diagnostic
from prompt_policy import render_prompt
checks=[]

def check(name,truth):
 assert truth,name
 checks.append(name)


def inputs(path):
 for folder in ('0','constant','system'):(path/folder).mkdir(parents=True,exist_ok=True)
 (path/'system/controlDict').write_text('endTime 1;\ndeltaT 1;\n')


message='--> FOAM FATAL ERROR: unknown input\nUnknown model type example\nValid types are:\n(a b c)\n\n From implementation/file.C\n[stack trace]\n#1 internal path'
d=failure_diagnostic(message,'log.offbeat')
check('诊断保留原生错误及合法类型',all(s in d['message'] for s in ['unknown input','Valid types','(a b c)']))
check('诊断不展开实现堆栈','file.C' not in d['message'] and '#1' not in d['message'])
check('诊断输出有界',len(failure_diagnostic('FOAM FATAL ERROR\n'+'x'*10000,'log')['message'])<=2200)
with tempfile.TemporaryDirectory(prefix='recovery-check-') as temp:
 root=Path(temp);old=root/'failed';inputs(old)
 fail="from pathlib import Path; import sys; p=Path('.'); (p/'1').mkdir(); (p/'log.offbeat').write_text("+repr(message)+");sys.exit(1)"
 failed=run_case(old,command=[sys.executable,'-c',fail])
 check('终态目录不能掩盖失败',failed['status']=='failed' and failed['exit_code']==1 and failed['final_time']=='1')
 check('失败返回定点错误摘要','Valid types' in failed['diagnostic']['message'])
 hash_before=hashlib.sha256((old/'.mandifuel-execution.json').read_bytes()).hexdigest()
 reused=run_case(old,command=[sys.executable,'-c',"raise RuntimeError('MUST NOT RUN')"])
 check('同目录重复调用保持幂等',reused==failed and hashlib.sha256((old/'.mandifuel-execution.json').read_bytes()).hexdigest()==hash_before)
 repaired=root/'repaired';inputs(repaired)
 success="from pathlib import Path; p=Path('.'); (p/'1').mkdir();(p/'log.offbeat').write_text('Time = 1\\nend\\n')"
 done=run_case(repaired,command=[sys.executable,'-c',success])
 check('新尝试可以正常完成',done['status']=='completed' and done['exit_code']==0)
 check('修复不覆盖旧失败凭据',hashlib.sha256((old/'.mandifuel-execution.json').read_bytes()).hexdigest()==hash_before)
 for cap in (None,2,0):
  work=root/('cap-'+str(cap));work.mkdir();inputs(work/'case');bindir=work/'bin';bindir.mkdir()
  wrapper=bindir/'offbeat';shutil.copy2(ROOT/'benchmarks/candidate-pairs/solver-wrapper.py',wrapper)
  fake=work/'fake_solver.py'
  fake.write_text("#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\np=Path("+repr(str(work/'count'))+")\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nprint('FOAM FATAL ERROR: test-only input failure' if n<4 else 'end')\nsys.exit(1 if n<4 else 0)\n")
  fake.chmod(0o755)
  (bindir/'config.json').write_text(json.dumps({'workspace':str(work),'solver_start_cap':cap,'real_binary':str(fake)}))
  codes=[subprocess.run([sys.executable,str(wrapper)],cwd=work/'case',capture_output=True).returncode for _ in range(4)]
  starts=(work/'solver-starts.jsonl').read_text().splitlines() if (work/'solver-starts.jsonl').exists() else []
  if cap is None:check('无限模式前三次失败后仍可第四次成功',codes==[1,1,1,0] and len(starts)==4)
  elif cap==2:check('显式用户上限仍被执行',codes==[1,1,75,75] and len(starts)==2)
  else:check('仅准备任务仍禁止启动',codes==[75]*4 and not starts)
 bank=ROOT/'benchmarks/2026-11-12-candidate-bank'
 entries=json.loads((bank/'candidates.json').read_text())['tasks']
 for t in entries:
  text=(bank/t['prompt_file']).read_text();effective,policy=render_prompt(text,t['solver_start_cap'],None)
  if t['solver_start_cap']==0:check(t['id']+'零启动范围保持',effective==text and policy['effective_cap']==0)
  elif t['solver_start_cap'] is None:check(t['id']+'无题面限额时不注入环境尾注',effective==text and policy['effective_cap'] is None)
  else:check(t['id']+'旧版默认无限且不包含专题答案',policy['effective_cap'] is None and '不设次数上限' in effective and ('fuelRodGap' not in effective or 'fuelRodGap' in text))
 original=(bank/'prompts/C08.txt').read_text();effective,policy=render_prompt(original,2,None)
 check('C08物理要求保留',all(s in effective for s in ['18000 W/m','300 K','Euler','步长 1 s','外边界全部绝热','内部导热耦合保留']))
 check('C08旧启动上限撤销','真实启动至多 2 次' not in effective and '预算不够或运行失败' not in effective)
 check('C08未注入修复答案',all(s not in effective for s in ['FRAPCON','mechanicsSolver','fuelRodGap']))
 result={'passed':len(checks),'checks':checks,'real_OFFBEAT_starts':0,'fake_solver_only':True}
 print(json.dumps(result,ensure_ascii=False,indent=2))
