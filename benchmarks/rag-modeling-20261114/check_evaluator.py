#!/usr/bin/env python3
"""在临时副本验证核对器的合法/非法输入分支，不改运行产物，不启动OFFBEAT。"""
import copy
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('rag_model_evaluator',HERE/'evaluate.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
root=Path(sys.argv[1]).resolve();verified=json.loads((root/'verification.json').read_text());checks=[]
with tempfile.TemporaryDirectory(prefix='rag-model-eval-test-') as directory:
    fixture=Path(directory);work=fixture/'G02/skill/workspace';(work/'retrieval').mkdir(parents=True)
    (work/'retrieval/result.out').write_text('local command prefix\n'+json.dumps({'interface':'mandifuel-rag-query.v2','mode':'local','provider_telemetry':{'network_requests':0},'candidates':[{'card_path':'Cases/Verification/example'}]})+'\n')
    got,detail=api.evidence_common(fixture,'G02','skill',[])
    assert next(c for c in got if c['check']=='retrieval_result_saved')['passed'];checks.append('检索原文按JSON内容识别.out扩展名')
    assert next(c for c in got if c['check']=='retrieval_offline')['passed'];checks.append('离线遥测嵌套字段正确识别')
    angle=math.radians(1);R=.00035;vertices=[[R,x*R*math.tan(angle),y*R*math.tan(angle)] for x in (-1,1) for y in (-1,1)]+[[0,0,0]]
    tolerance=api.geometry_tolerance(vertices);radius=max(math.sqrt(sum(v*v for v in p)) for p in vertices)
    assert math.isclose(radius,R,rel_tol=tolerance);checks.append('小角度楔的角点与轴截面半径约定差异被接受')
    assert not math.isclose(radius*1.02,R,rel_tol=tolerance);checks.append('同一楔角不会放过2%的真实尺寸错误')
    original=verified['tasks']['M01']['skill'];entry=next(x for x in original['case_checks'] if x['passed']);event=copy.deepcopy(next(x for x in original['executions'] if x['id']==entry['event_id']))
    evidence=fixture/'evidence';shutil.copytree(Path(event['evidence_dir']),evidence);event['evidence_dir']=str(evidence)
    cache=fixture/'geometry';shutil.copytree(root/'独立几何核对'/event['id'],cache/event['id'])
    req=next(t for t in json.loads((root/'tasks.json').read_text())['tasks'] if t['id']=='M01')['requirements']
    good=api.m01_event(event,cache,req);assert good['passed'],good;checks.append('真实保留场正例通过')
    end=api.terminal(event);(end/'diffCs').write_text('FoamFile {version 2.0;format ascii;class volScalarField;object diffCs;} dimensions [0 2 -1 0 0 0 0];internalField uniform 1e-13;boundaryField {}')
    bad=api.m01_event(event,cache,req);assert not next(c for c in bad['checks'] if c['check']=='effective_diffusivity_2_5e_14')['passed'];checks.append('实际扩散系数错误被拒绝')
    p=cache/event['id']/'geometry.json';d=json.loads(p.read_text());d['vertices']=[[1.02*x for x in v] for v in d['vertices']];p.write_text(json.dumps(d))
    bad=api.m01_event(event,cache,req);assert not next(c for c in bad['checks'] if c['check']=='target_solid_sphere_radius')['passed'];checks.append('真实场夹具中的尺寸错误被拒绝')
print(json.dumps({'passed':len(checks),'checks':checks,'scope':'临时副本/合成检索，仅核对判分逻辑；不参与实际实验得分','solver_starts':0,'retained_inputs_modified':False},ensure_ascii=False,indent=2))
