#!/usr/bin/env python3
"""用明确标注的合成场验证C05判分的正反分支；不启动模型或求解。"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/candidate-pairs'))
import evaluate_suite as evaluator
import capability_task_checks as subject
foam=evaluator.foam
source=Path('/home/lwz/offbeat/Cases/Verification/trisoModulesTest/testSiC_creep')
checks=[]
headers=['time_s','epsilonCreep_xx']
with tempfile.TemporaryDirectory(prefix='c05-evaluator-test-') as directory:
    work=Path(directory);before=work/'evidence/before';case=work/'case';terminal=case/'2e8'
    terminal.mkdir(parents=True)
    for name in ('T','epsilon','epsEl','epsilonCreep'):(terminal/name).touch()
    solver=foam.read_foam(source/'constant/solverDict');T=foam.read_foam(source/'0/T');D=foam.read_foam(source/'0/D');geometry=foam.read_foam(source/'system/blockMeshDict')
    documents={str(before/'constant/solverDict'):solver,str(work/'source-case/constant/solverDict'):copy.deepcopy(solver),str(before/'0/T'):T,str(before/'0/D'):D,str(case/'system/blockMeshDict'):geometry,str(work/'source-case/system/blockMeshDict'):copy.deepcopy(geometry)}
    fields={}
    for name,values in [('T',[600]),('epsilon',[.006,0,0,0,0,0]),('epsEl',[.005,0,0,0,0,0]),('epsilonCreep',[.001,0,0,0,0,0])]:
        fields[name]={'values':values,'components':1 if name=='T' else 6,'min':min(values),'max':max(values),'dimensions':['[','0','0','0','0','0','0','0',']']}
    event={'normal':True,'physical_last_time_s':2e8,'case_root':str(case),'evidence_dir':str(work/'evidence'),'factor':1}
    def run():
        local=[]
        def check(items,name,passed,**evidence):items.append({'check':name,'passed':bool(passed),**evidence})
        api={'check':check,'foam':foam,'field':lambda p:copy.deepcopy(fields[p.name]),'number':evaluator.number,'times':lambda p:[(2e8,terminal)]}
        with patch.object(foam,'read_foam',side_effect=lambda p:copy.deepcopy(documents[str(p)])),patch.object(subject,'tables',return_value=[{'rows':3,'columns':headers,'file':'strain_history.csv'}]),patch.object(subject,'artifacts',return_value='xx elastic dimensionless'):
            return subject.c05(work,[event],local,api)
    result=run();assert result['status']=='completed',result;checks.append('合成合法输入和应变分解通过')
    headers[0]='t_s'
    result=run();assert result['status']=='completed',result;checks.append('通用t_s时间列同样接受')
    fields['epsilon']['values'][0]=.008
    result=run();assert not next(c for c in result['checks'] if c['check']=='total_equals_elastic_plus_creep_with_serialization_tolerance')['passed'];checks.append('应变不闭合失败')
    fields['epsilon']['values'][0]=.006
    fields['T']['min']=fields['T']['max']=700
    result=run();assert not next(c for c in result['checks'] if c['check']=='final_temperature_600K')['passed'];checks.append('温度错误失败')
    fields['T']['min']=fields['T']['max']=600
    documents[str(before/'constant/solverDict')]['fastFluxOptions']['fastFlux']=['(','1','1',')']
    result=run();assert not next(c for c in result['checks'] if c['check']=='source_fast_flux_preserved')['passed'];checks.append('快通量被改动失败')
    result=subject.c05(work,[],[],{'check':lambda items,name,passed,**e:items.append({'check':name,'passed':passed}),'foam':foam,'field':None,'number':None,'times':None})
    assert result['status']=='incomplete';checks.append('无正常执行不能通过')
print(json.dumps({'fixture':'合成字段，只验证判分逻辑，不用于真实实验得分','passed':len(checks),'checks':checks,'solver_starts':0,'model_requests':0},ensure_ascii=False,indent=2))
