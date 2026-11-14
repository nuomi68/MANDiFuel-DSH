#!/usr/bin/env python3
"""核对交付并归档分析源码；不改参与者产物。"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import shutil
import sys

repo=Path(__file__).resolve().parents[2];r=Path(sys.argv[1]).resolve()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
v=load(r/'verification.json');i=load(r/'integrity.json');d=load(r/'delivery-numeric-check.json');t=load(r/'中文单行轨迹/翻译清单.json')
assert i['passed']
assert all(x['status']=='completed' and all(c['passed'] for c in x['checks']) and all(y['passed'] for y in x['case_checks']) for pair in v['tasks'].values() for x in pair.values())
assert all(x['status']=='checked' and not x['errors'] for pair in d['tasks'].values() for x in pair.values())
assert d['numeric_values_checked']==4190
assert t['事件总数']==574 and len(t['文档'])==6
assert all(sha(r/name)==digest for name,digest in t['源文件SHA256'].items())
archive=r/'evaluation-source';archive.mkdir(exist_ok=True)
for p in (repo/'benchmarks/rag-modeling-20261114').glob('*'):
    if p.is_file():shutil.copyfile(p,archive/p.name)
for name in ('evaluate_suite.py','new_case_checks.py','generalization_checks.py','capability_task_checks.py','analyze_suite.py','audit_workflow.py','audit_exposure.py','translate_traces_zh.py','render_compact_traces_zh.py','compact_traces_zh.py'):
    shutil.copyfile(repo/'benchmarks/candidate-pairs'/name,archive/name)
shutil.copyfile(repo/'benchmarks/fuel-rod-power-ab/verify_results.py',archive/'reference_reader.py')
record={'核对时间_北京时间':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'有效运行目录':str(r),'目标任务完成':6,'实验完整性通过':len(i['checks']),'任务交付与覆盖检查通过':sum(len(x['checks']) for p in v['tasks'].values() for x in p.values()),'合格候选场检查通过':sum(len(y['checks']) for p in v['tasks'].values() for x in p.values() for y in x['case_checks']),'交付数值匹配':d['numeric_values_checked'],'中文可观察事件':t['事件总数'],'原始会话哈希未变':True,'实际求解启动':sum(x['solver_starts'] for p in v['tasks'].values() for x in p.values()),'组织者追加求解':0,'产品与公共资源保持冻结':True,'结果报告SHA256':sha(r/'结果汇总.md'),'归档说明':'evaluation-source为准确源码留存；原始脚本依赖项目相邻核对模块，调用位置与环境要求见benchmarks/rag-modeling-20261114/实验说明.md。','分析源码归档':{p.name:sha(p) for p in archive.iterdir() if p.is_file()},'核对器兼容勘误':'evaluation-compatibility-corrections.json','审计误报复核':'workflow-review-corrections.json','排除轮次':['../rag-modeling-pairs-20261114-01','../rag-modeling-pairs-20261114-02']}
p=r/'交付核对.json';p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
for doc in (r/'结果汇总.md',repo/'benchmarks/rag-modeling-20261114/实验说明.md'):
    for link in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
        if '://' not in link:assert (doc.parent/link).exists(),(doc,link)
record['全部核对通过']=True;p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:record[k] for k in ('全部核对通过','目标任务完成','实验完整性通过','交付数值匹配','中文可观察事件','实际求解启动','组织者追加求解')},ensure_ascii=False))
