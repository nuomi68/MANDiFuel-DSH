"""Publish existing multi-solve observations and their explicit model bindings."""
import argparse
import copy
import json
import hashlib
import re
from pathlib import Path
from registry import atomic,inside,read_json,validate_bundle
from study import validate_study

def lookup(value,path):
    for part in path.split('.'):
        if not isinstance(value,dict) or part not in value:return None
        value=value[part]
    return value

def history_study(history,config):
    """Map an existing Study history. Values are never inferred or re-computed."""
    if not isinstance(history,list):raise ValueError('历史必须是Study记录数组')
    study=copy.deepcopy(config);study.pop('models',None);study.pop('iterationSource',None);study['schema']='mandifuel.study/v1';runs=[]
    for index,record in enumerate(history):
        point=record.get('point',{});raw_id=str(point.get('id',index+1));ident=raw_id if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',raw_id) else 'run-'+hashlib.sha256(raw_id.encode()).hexdigest()[:20];status=record.get('status','queued')
        status=status if status in {'queued','running','completed','skipped'} else 'failed'
        run={'id':ident,'status':status,'parameters':{},'responses':{},'iteration':lookup(record,config['iterationSource']) if config.get('iterationSource') else index+1}
        for key in ('parameters','responses'):
            if key=='responses' and status!='completed':continue
            for definition in config[key]:
                source=definition.get('source',('point.' if key=='parameters' else 'reporting_response.')+definition['id'])
                if key=='responses' and source.startswith('reporting_response.') and record.get('reporting_status') not in {None,'completed'}:continue
                v=lookup(record,source)
                if v is not None:run[key][definition['id']]=v
        if record.get('error'):run['error']=str(record['error'])[:800]
        binding=config.get('models',{}).get(raw_id)
        if binding and status in {'completed','running'}:run.update(binding)
        runs.append(run)
    for key in ('parameters','responses'):
        for definition in study[key]:definition.pop('source',None)
    study['runs']=runs;return study

def export_study(workspace,output,study,views=()):
    work=Path(workspace).resolve();output=inside(work,str(output));output.parent.mkdir(parents=True,exist_ok=True)
    manifest_path=work/'delivery/workbench.json';manifest=read_json(manifest_path) if manifest_path.exists() else {'schema':'mandifuel.handoff/v1'}
    refs={r['id']:r for r in manifest.get('views',[])}
    if not refs and manifest.get('viewer'):refs['main']={'id':'main','label':'原有模型','viewer':manifest['viewer']}
    for ref in views:
        bundle=validate_bundle(read_json(inside(work,ref['viewer'])));inside(work,bundle['caseRoot']);refs[ref['id']]=ref
    value=validate_study(study,refs)
    for run in value['runs']:
        if 'caseRoot' in run:
            root=inside(work,run['caseRoot'])
            for key in run['viewIds']:
                b=read_json(inside(work,refs[key]['viewer']))
                if inside(work,b['caseRoot'])!=root:raise ValueError('参数组与模型的计算目录不一致')
    atomic(output,value);manifest['study']=str(output.relative_to(work));manifest['views']=list(refs.values());manifest.pop('viewer',None)
    if refs and manifest.get('defaultView') not in refs:manifest['defaultView']=next(iter(refs))
    manifest_path.parent.mkdir(parents=True,exist_ok=True);atomic(manifest_path,manifest)
    return value

def main():
    p=argparse.ArgumentParser(description='登记已有扫描、优化或不确定度结果；不启动求解器')
    p.add_argument('--definition',required=True,help='含study与views的JSON定义')
    p.add_argument('--history',help='可选：已有Study history.json，study字段作为映射配置')
    p.add_argument('--workspace',default='.')
    p.add_argument('--output',default='delivery/study.json')
    a=p.parse_args();work=Path(a.workspace).resolve();definition=read_json(inside(work,a.definition));study=definition['study']
    if a.history:study=history_study(read_json(inside(work,a.history)),study)
    value=export_study(work,a.output,study,definition.get('views',[]));print(f"已登记{len(value['runs'])}组；类型{value['kind']}；未启动求解器")
if __name__=='__main__':main()
