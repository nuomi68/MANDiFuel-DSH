#!/usr/bin/env python3
"""Read-only API profiling after all timed sessions have exited; no solve."""
import argparse
import cProfile
from datetime import datetime
import importlib
import json
from pathlib import Path
import pstats
import sys
import time
from zoneinfo import ZoneInfo

p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);args=p.parse_args();root=args.run_root.resolve();manifest=json.loads((root/'manifest.json').read_text())
if not all('ended_at_utc' in r for r in manifest['results']):raise SystemExit('Timed sessions must finish first')
sys.path.insert(0,str(root/'frozen-plugin/skills/extract-offbeat-results/scripts'))
api=importlib.import_module('result_api')
case=root/'W01/skill/workspace/cases/A'
def sample():return api.read_field(case,'T',time='1576800',scope=('cellZone','fuel'),component='value',include_volumes=True)
measurements=[]
for _ in range(3):
 began=time.perf_counter();frame=sample();measurements.append(time.perf_counter()-began)
profile=cProfile.Profile();profile.enable();sample();profile.disable()
stat=pstats.Stats(profile);top=[]
for (file,line,name),(primitive,total,own,cumulative,callers) in sorted(stat.stats.items(),key=lambda item:item[1][3],reverse=True)[:25]:
 top.append({'file':file,'line':line,'function':name,'primitive_calls':primitive,'total_calls':total,'own_seconds':own,'cumulative_seconds':cumulative})
out={'checked_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'scope':'全部计时会话退出后的只读采样；不计入实验墙钟，不调用求解器','api':'result_api.read_field','selection':{'case':str(case),'variable':'T','time':'1576800','scope':['cellZone','fuel'],'include_volumes':True},'selected_cells':len(frame.values),'three_identical_reads_seconds':measurements,'cprofile_top_cumulative':top,'interpretation':'相同不可变输入重复读取的单次实测；静态脚本循环次数不能直接等同真实调用计数，cProfile附带额外开销'}
(root/'extraction-profile.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
profile.dump_stats(str(root/'extraction-profile.pstats'))
print(json.dumps({'reads_seconds':measurements,'cells':len(frame.values),'top_functions':[t['function'] for t in top[:8]]},ensure_ascii=False))
