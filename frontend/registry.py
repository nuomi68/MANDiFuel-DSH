"""Task workspaces and verified deliveries; native DSH owns every session."""
from __future__ import annotations
from collections import deque,OrderedDict
from datetime import datetime,timezone
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid

from progress_history import current_progress,record_progress

REPO=Path(__file__).resolve().parents[1]
RUNNING={'queued','starting','running','importing'}
MAX_JSON=64*1024*1024
SOLVER_GUIDANCE='你是 OFFBEAT 计算运行助手。使用准备好的 MANDiFuel Skills 与本地资源，不联网，不查看或修改求解器、插件和解析器实现。按用户请求独立完成输入准备、网格、求解、结果提取与报告。resources.md 提供资料。保留实际输入、结果根、运行回执及必要脚本；扫描、优化和不确定度使用已有 Study 工作流记录参数计划、候选、状态与真实响应。遵守用户给定的预算、停止条件和失败处理要求。\n'


def now():return datetime.now(timezone.utc).isoformat()
def latest_request(meta):return meta.get('latestDisplayPrompt') or meta.get('latestPrompt') or meta.get('prompt','')
def read_json(path):
    if path.stat().st_size>MAX_JSON:raise ValueError('交付文件超过 64 MB，请拆分结果')
    return json.loads(path.read_text(),parse_constant=lambda s:(_ for _ in ()).throw(ValueError('非有限数值')))
def atomic(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False));temp.replace(path)
def inside(root,value):
    path=Path(value);path=(root/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('文件路径必须位于本任务工作区内')
    return path

def validate_mesh(mesh,count):
    def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    points=mesh['points'];triangles=mesh['triangles'];cells=mesh['cells']
    if not isinstance(count,int) or isinstance(count,bool) or count<=0:raise ValueError('单元数量无效')
    if not points or any(len(p)!=3 or not all(number(v) for v in p) for p in points):raise ValueError('网格坐标无效')
    if not triangles or len(triangles)%3 or len(cells)!=len(triangles)//3:raise ValueError('网格面值映射无效')
    if any(not isinstance(i,int) or isinstance(i,bool) or not 0<=i<len(points) for i in triangles):raise ValueError('网格索引越界')
    if any(not isinstance(i,int) or isinstance(i,bool) or not 0<=i<count for i in cells):raise ValueError('单元索引越界')
    if 'cellCenters' in mesh and (len(mesh['cellCenters'])!=count or any(len(p)!=3 or not all(number(v) for v in p) for p in mesh['cellCenters'])):raise ValueError('极值标注的单元中心无效')
    if 'reconstruction' in mesh:
        r=mesh['reconstruction'];angle=r.get('angle')
        if r.get('type')!='axisymmetric-revolve' or r.get('axis') not in {'x','y','z'} or not number(angle) or not 0<angle<=360 or r.get('sourceDimension')!=2:raise ValueError('轴对称旋转重建元数据无效')
    if 'cellEdges' in mesh:
        if len(mesh['cellEdges'])!=count or any(not edges or len(edges)%2 or any(not isinstance(i,int) or isinstance(i,bool) or not 0<=i<len(points) for i in edges) for edges in mesh['cellEdges']):raise ValueError('单元切片拓扑无效')

def validate_bundle(bundle):
    if bundle.get('schema')=='mandifuel.mesh/v1':
        if bundle['task'].get('fields') or bundle['data'].get('kind')!='mesh':raise ValueError('网格预览不能包含伪结果场')
        validate_mesh(bundle['data']['mesh'],bundle['task']['cells']);return bundle
    if bundle.get('schema')!='mandifuel.viewer/v1':raise ValueError('可视化格式不受支持')
    meta=bundle['task'];data=bundle['data'];variables=meta['fields'];r=data['r'];frames=data['frames']
    if meta['shape'] not in {'mesh','sphere','shell','rod'} or not variables or not frames or not r:raise ValueError('结果结构不完整')
    def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    if not all(number(v) for v in r):raise ValueError('径向坐标无效')
    if meta.get('cells')!=len(r):raise ValueError('单元数量与场值不匹配')
    if any(not isinstance(v.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',v['id']) for v in variables):raise ValueError('字段标识无效')
    if len({v['id'] for v in variables})!=len(variables):raise ValueError('字段标识重复')
    if not number(meta.get('radius')) or meta['radius']<=0:raise ValueError('外半径无效')
    inner=meta.get('innerRadius',0)
    if not number(inner) or not 0<=inner<meta['radius']:raise ValueError('内半径无效')
    if meta['shape']=='rod' and (not number(meta.get('length')) or meta['length']<=0):raise ValueError('棒长无效')
    if 'radialBands' in meta:
        previous=inner;total=0
        for a,b,n in meta['radialBands']:
            if not number(a) or not number(b) or not previous<=a<b<=meta['radius'] or not isinstance(n,int) or isinstance(n,bool) or n<=0:raise ValueError('径向材料区无效：只列实体区域，空隙省略；每区格数必须大于0；radius 必须是整个模型最外层半径')
            previous=b;total+=n
        if total!=len(r):raise ValueError('径向材料区与单元数不匹配')
    for v in variables:
        a,b=v['range']
        if not number(a) or not number(b) or b<=a:raise ValueError('色标范围无效')
    for frame in frames:
        if not number(frame['time']):raise ValueError('时间无效')
        for v in variables:
            values=frame['fields'][v['id']]
            if len(values)!=len(r) or not all(number(x) for x in values):raise ValueError('场值与单元数量不匹配')
        if meta['shape']=='mesh':
            validate_mesh(data['meshes'][frame['mesh']],len(r))
            mesh=data['meshes'][frame['mesh']]
            if meta.get('reconstruction')!=mesh.get('reconstruction'):raise ValueError('重建声明与实际几何不一致')
            if meta.get('supportsExtrema') and not mesh.get('cellCenters'):raise ValueError('极值标注缺少真实单元中心')
    if meta['shape']!='mesh' and any(a>b for a,b in zip(r,r[1:])):raise ValueError('径向坐标必须递增')
    return bundle

class TaskRegistry:
    """Only task workspaces and deliveries. Sessions and chat belong to native DSH."""
    def __init__(self,root=None,sources=None):
        self.root=Path(root or REPO/'runs/workbench').resolve();self.root.mkdir(parents=True,exist_ok=True);self.sources=sources or {};self.lock=threading.RLock();self.condition=threading.Condition(self.lock);self.jobs={};self.shutting_down=False;self.view_cache=OrderedDict()
        for p in self.root.glob('*/task.json'):
            try:
                meta=read_json(p);bundle=validate_bundle(read_json(p.parent/'bundle.json')) if (p.parent/'bundle.json').exists() and not meta.get('study') else None
                if meta['status'] in RUNNING:meta['status']='interrupted'
                meta['sessionStates']={}
                views=read_json(p.parent/'views.json') if (p.parent/'views.json').exists() else ({'main':{'label':'计算结果','bundle':bundle}} if bundle else {})
                for view in views.values():
                    if 'bundle' in view:validate_bundle(view['bundle'])
                    else:inside(p.parent/'workspace',view['source'])
                self.jobs[meta['id']]={'meta':meta,'workspace':p.parent.resolve()/'workspace','bundle':bundle,'views':views,'journal':deque(maxlen=1000),'seq':0}
                if 'progressHistory' not in meta:
                    meta['progressHistory']=[];meta['progressHistoryComplete']=False
                    record_progress(meta,timestamp=meta.get('updatedAt',meta.get('createdAt')),restored=True);self._save(self.jobs[meta['id']])
            except (ValueError,KeyError,OSError):continue
        # Retire the previously generated UI instructions without changing case
        # inputs or rewriting historical session transcripts.
        for job in self.jobs.values():
            work=job['workspace'];instructions=work/'AGENTS.md'
            if instructions.is_file() and instructions.read_text().startswith('你是 OFFBEAT 计算运行助手。') and 'WORKBENCH.md' in instructions.read_text():
                archive=work.parent/'presentation-legacy';archive.mkdir(exist_ok=True)
                for name in ['AGENTS.md','resources.md','WORKBENCH.md','STUDY_HANDOFF.md']:
                    source=work/name
                    if source.is_file() and not (archive/name).exists():shutil.copy2(source,archive/name)
                instructions.write_text(SOLVER_GUIDANCE)
                resources=work/'resources.md'
                if resources.exists():resources.write_text('\n'.join(line for line in resources.read_text().splitlines() if 'WORKBENCH.md' not in line and 'STUDY_HANDOFF.md' not in line)+'\n')
                for name in ['WORKBENCH.md','STUDY_HANDOFF.md']:
                    if (work/name).is_file():(work/name).unlink()
        # Reconcile externally regenerated deliveries with the retained cache,
        # including stopped tasks, before the first browser response.
        for job in self.jobs.values():
            before=copy.deepcopy(job['meta']);self._import(job,missing_ok=True)
            if job['meta']!=before:self._save(job)
        from presentation import Dashboard
        self.dashboard=Dashboard(self)
        from process_monitor import ProcessMonitor
        self.process_monitor=ProcessMonitor(self)
        from evidence import EvidenceService
        self.evidence=EvidenceService(self)
    def _job(self,ident):
        if ident not in self.jobs:raise KeyError('任务不存在')
        return self.jobs[ident]
    def _save(self,job):
        job['meta']['stateVersion']=job['meta'].get('stateVersion',0)+1
        record_progress(job['meta']);atomic(job['workspace'].parent/'task.json',job['meta'])
    def _emit(self,job,kind,data):job['seq']+=1;job['journal'].append({'id':job['seq'],'kind':kind,'data':copy.deepcopy(data)});self.condition.notify_all()
    def public(self,job):
        m=job['meta'];bundle=job['bundle'];views=job.get('views',{});primary=views.get(m.get('defaultView')) or next(iter(views.values()),None)
        primary_schema=bundle['schema'] if bundle else primary.get('schema') if primary else None
        primary_task=bundle['task'] if bundle else primary.get('task') if primary else None
        result={'id':m['id'],'title':m['title'],'status':m['status'],'runtime':True,'nativeSessionId':m.get('nativeSessionId'),'nativeWorkspaceId':m.get('nativeWorkspaceId'),'nativeSessionIds':m.get('nativeSessionIds',[]),'draft':m.get('draft',False),'description':m['prompt'][:80],'resultReady':primary_schema=='mandifuel.viewer/v1','modelReady':bool(primary_task),'previewReady':primary_schema=='mandifuel.mesh/v1','modelVersion':m.get('modelVersion',m.get('resultVersion',0)),'resultVersion':m.get('resultVersion',0),'createdAt':m['createdAt'],'updatedAt':m['updatedAt'],'error':m.get('error'),'importError':m.get('importError'),'presentationError':m.get('presentationError'),'cells':0,'fields':[],'shape':'mesh','duration':max(0,time.time()-datetime.fromisoformat(m['createdAt']).timestamp()),'solverStarts':None,'eventCount':len(m.get('events',[])),'inputCount':len(m.get('inputs',[])),'fileCount':len(m.get('files',[]))}
        if primary_task:result.update(primary_task)
        presentation=copy.deepcopy(m.get('presentation',{}))
        viewrows=[{'id':key,'label':v['label'],'kind':'mesh' if (v['bundle']['schema'] if 'bundle' in v else v['schema'])=='mandifuel.mesh/v1' else 'results','task':copy.deepcopy(v['bundle']['task'] if 'bundle' in v else v['task']),'version':'-'.join(map(str,v['stamp'])) if v.get('stamp') else m.get('modelVersion',0)} for key,v in views.items()]
        for row in viewrows:
            view=views[row['id']]
            from source_metadata import case_time_unit
            try:
                case=inside(job['workspace'],view.get('caseRoot') or view.get('bundle',{}).get('caseRoot',''))
                row['caseRoot']=str(case.relative_to(job['workspace'].resolve()))
                verified_unit=case_time_unit(case)
                if verified_unit:row['task']['timeUnit']=verified_unit
            except (OSError,ValueError):pass
            if 'coordinateBounds' not in view and 'bundle' in view:
                data=view['bundle']['data'];mesh=data.get('mesh')
                if mesh is None and data.get('meshes') and data.get('frames'):mesh=data['meshes'].get(data['frames'][0].get('mesh'))
                if mesh and mesh.get('points'):
                    view['coordinateBounds']={'min':[min(p[i] for p in mesh['points']) for i in range(3)],'max':[max(p[i] for p in mesh['points']) for i in range(3)],'unit':'m','time':data.get('frames',[{}])[0].get('time')}
            if view.get('coordinateBounds'):row['task']['coordinateBounds']=copy.deepcopy(view['coordinateBounds'])
            if row['task'].get('supportsSlice') and 'bundle' in view:
                data=view['bundle']['data']
                limitations=[{'time':frame['time'],'nonConvexCells':len(data.get('meshes',{}).get(frame.get('mesh'),{}).get('nonConvexCells',[]))} for frame in data.get('frames',[])]
                if any(item['nonConvexCells'] for item in limitations):row['task']['sliceLimitations']=limitations
        primary_row=next((row for row in viewrows if row['id']==m.get('defaultView')),None)
        if primary_row and primary_row['task'].get('timeUnit'):result['timeUnit']=primary_row['task']['timeUnit']
        from presentation import default_controls
        from ui_policy import clean_document
        if presentation.get('ui'):presentation['ui'],_=clean_document(presentation['ui'])
        presentation.pop('progress',None)
        presentation.setdefault('controls',default_controls(result,viewrows,presentation.get('rendering')))
        result.update(id=m['id'],title=m['title'],status=m['status'],presentation=presentation,presentationVersion=m.get('presentationVersion',0),views=viewrows,defaultView=m.get('defaultView','main'),presenter=copy.deepcopy(m.get('presenter',{})))
        if m.get('study'):
            from study import summary
            result['study']=summary(m['study'],m.get('studyVersion',0))
        else:result['study']=None
        result.update(workspaceRevision=m.get('workspaceWatch',{}).get('revision',0),progress=current_progress(m),progressCount=sum(row.get('source')=='process-observer' for row in m.get('progressHistory',[])),progressVersion=sum(row.get('source')=='process-observer' for row in m.get('progressHistory',[])),deliveryVersion=m.get('deliveryVersion',0),artifactCount=len({f['path'] for f in m.get('inputs',[])+m.get('files',[])}))
        result['stateVersion']=m.get('stateVersion',0)
        case_events=[e for e in m.get('workspaceWatch',{}).get('events',[]) if e.get('kind')=='case']
        result['modelExpected']=bool(primary_task or result['study'] or case_events or m.get('processState',{}).get('cases') or m['status']!='completed')
        result['evidence']=copy.deepcopy(m.get('evidence',{}))
        result.pop('code',None);return result
    def list(self):
        with self.lock:return [self.public(j) for j in sorted(self.jobs.values(),key=lambda j:j['meta']['createdAt'],reverse=True)]
    def snapshot(self,ident):
        with self.lock:
            job=self._job(ident);return {'task':self.public(job),'cursor':job['seq'],'inputs':copy.deepcopy(job['meta'].get('inputs',[])),'files':copy.deepcopy(job['meta'].get('files',[]))}
    def prepare(self,prompt,title='',source=None,*,draft=False):
        prompt=prompt.strip()
        if (not prompt and not draft) or len(prompt)>60000:raise ValueError('请输入 1–60000 字的任务描述')
        ident='task-'+uuid.uuid4().hex[:16];folder=self.root/ident;work=folder/'workspace';work.mkdir(parents=True)
        if source:
            with self.lock:
                if source in self.jobs:
                    source_job=self.jobs[source];b=source_job['bundle']
                    if not b and source_job.get('views'):b=self._view_bundle(source_job,source_job['meta'].get('defaultView'))
                    case=inside(source_job['workspace'],b['caseRoot']) if b else None
                else:case=Path(self.sources[source]) if source in self.sources else None
            if case is None or not case.is_dir():raise ValueError('当前模型没有可复用的输入卡')
            target=work/'source-case';target.mkdir()
            for name in ('0','constant','system'):
                if (case/name).is_dir():shutil.copytree(case/name,target/name)
            for name in ('Allrun','rodDict','sphereDict','rod3Ddict.json','input_settings.txt','timesteps'):
                if (case/name).is_file():shutil.copy2(case/name,target/name)
        (work/'AGENTS.md').write_text(SOLVER_GUIDANCE)
        (work/'request.txt').write_text(prompt)
        (work/'resources.md').write_text(f'插件: {REPO}\n本地算例与经验联合检索: {REPO}/rag/experience/dual_query.py\n审核经验检索: {REPO}/rag/experience/experience_rag.py query\n'+('source-case/ 是当前模型输入副本。\n' if source else '按请求使用本地 RAG 准备算例。\n'))
        meta={'id':ident,'title':(title.strip() or (prompt.splitlines()[0] if prompt else '新任务'))[:24],'prompt':prompt,'status':'draft' if draft else 'queued','draft':draft,'createdAt':now(),'updatedAt':now(),'nativeSessionId':None,'events':[],'progressHistory':[],'progressHistoryComplete':True,'inputs':[],'files':[],'resultVersion':0}
        job={'meta':meta,'workspace':work,'bundle':None,'views':{},'journal':deque(maxlen=1000),'seq':0}
        with self.lock:self.jobs[ident]=job;self._save(job)
        return dict(self.snapshot(ident),workspace=str(work),prompt=prompt)
    def bind(self,ident,session_id,workspace_id=None):
        with self.lock:
            job=self._job(ident);job['meta']['nativeSessionId']=session_id
            if workspace_id:job['meta']['nativeWorkspaceId']=workspace_id
            ids=job['meta'].setdefault('nativeSessionIds',[])
            if session_id not in ids:ids.append(session_id)
            self._save(job)
        return self.snapshot(ident)
    def draft(self):
        with self.lock:
            for job in self.jobs.values():
                if job['meta'].get('draft') and job['meta']['status']=='draft' and job['workspace'].resolve().is_relative_to(self.root):
                    return dict(self.snapshot(job['meta']['id']),workspace=str(job['workspace']),prompt='')
            return self.prepare('',title='新任务',draft=True)
    def adopt(self,cwd,session_id):
        with self.lock:
            for ident,job in self.jobs.items():
                if Path(cwd).resolve()==job['workspace'].resolve():self.bind(ident,session_id);return {'taskId':ident}
        return {'taskId':None}
    def native_event(self,ident,payload):
        with self.lock:
            job=self._job(ident);meta=job['meta'];kind=payload['kind'];meta['updatedAt']=now()
            if kind=='title':
                title=payload.get('title')
                if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('DSH 会话标题无效')
                sid=payload.get('sessionId')
                if sid and sid not in [meta.get('nativeSessionId'),*meta.get('nativeSessionIds',[])]:raise ValueError('DSH 会话标题不属于本任务')
                meta['title']=title.strip();meta['nativeTitle']=title.strip()
            elif kind=='prompt':
                text=payload.get('text','').strip()
                if text:
                    meta.pop('latestDisplayPrompt',None)
                    meta['latestPrompt']=text;meta['promptRevision']=meta.get('promptRevision',0)+1
                    presentation=dict(meta.get('presentation',{}));presentation.pop('deliveryRequirements',None);presentation['progress']={'summary':'正在处理新请求' if meta['promptRevision']>1 else '正在准备任务','stages':[]};meta['presentation']=presentation;meta['presentationVersion']=meta.get('presentationVersion',0)+1
                    if meta.get('draft'):meta.update(prompt=text,title=text.splitlines()[0][:24],draft=False);(job['workspace']/'request.txt').write_text(text)
            elif kind=='display-prompt':
                text=payload.get('text','').strip()
                if not text:raise ValueError('显示请求不能为空')
                meta['latestDisplayPrompt']=text;meta['displayPromptRevision']=meta.get('displayPromptRevision',0)+1
                presentation=dict(meta.get('presentation',{}));presentation.pop('deliveryRequirements',None);meta['presentation']=presentation;meta['presentationVersion']=meta.get('presentationVersion',0)+1
                meta['presenter']={'state':'queued','message':'等待更新展示'}
            elif kind=='failure':
                meta['status']='failed';meta['error']=payload.get('error','原生会话创建失败');presentation=dict(meta.get('presentation',{}));presentation['progress']={'summary':'本轮执行失败','stages':[]};meta['presentation']=presentation;meta['presentationVersion']=meta.get('presentationVersion',0)+1
            elif kind=='tool':
                meta['events'].append({'id':len(meta['events'])+1,'turn':payload.get('turn',0),'time':payload.get('time',''),'action':payload.get('action','工具操作'),'diagnostics':[]})
            elif kind=='turn':meta['endReason']=payload.get('reason','completed')
            elif kind=='status':
                sid=payload.get('sessionId',meta.get('nativeSessionId','main'));states=meta.setdefault('sessionStates',{});states[sid]=payload['status']
                if payload['status']=='running':meta['status']='running';meta['error']=None
                elif meta['status']=='running' and 'running' not in states.values():
                    reason=meta.get('endReason','completed');meta['status']='completed' if reason=='completed' else 'stopped' if reason=='aborted' else 'failed';meta['error']=payload.get('error')
                    if reason=='completed':self._import(job)
                    progress=current_progress(meta)
                    if reason!='completed' or progress['summary'].startswith(('正在','等待','准备')) or any(s.get('status')=='active' for s in progress['stages']):
                        presentation=dict(meta.get('presentation',{}));presentation['progress']={'summary':'本轮处理结束，正在整理展示' if reason=='completed' else '任务已停止' if reason=='aborted' else '本轮执行失败','stages':[]};meta['presentation']=presentation;meta['presentationVersion']=meta.get('presentationVersion',0)+1
            from process_monitor import process_event
            process_event(meta,payload)
            self._save(job);self._emit(job,'state',self.public(job))
        return self.snapshot(ident)
    def _import(self,job,missing_ok=False):
        work=job['workspace'];path=work/'delivery/workbench.json';meta=job['meta'];watch_path=work/'delivery/workspace-observation.json'
        if not path.is_file() and not watch_path.is_file():
            if not missing_ok:meta['importError']='本轮尚未交付模型或文件。'
            return
        try:
            manifest=read_json(path) if path.is_file() else {'schema':'mandifuel.handoff/v1'}
            watch=read_json(watch_path) if watch_path.is_file() else {}
            if watch and watch.get('schema')!='mandifuel.workspace-observation/v1':raise ValueError('文件观察索引格式无效')
            if watch.get('study') and not manifest.get('study'):manifest['study']=watch['study']
            if manifest.get('schema')!='mandifuel.handoff/v1':raise ValueError('交付清单格式不受支持')
            from presentation import validate_presentation
            config=None;presentation_error=None
            if 'presentation' in manifest:
                try:config=validate_presentation(manifest['presentation'])
                except (ValueError,KeyError,TypeError) as error:presentation_error='显示配置未应用：'+str(error)
            refs=list(manifest.get('views',[]))
            if not refs and manifest.get('viewer'):refs=[{'id':'main','label':'计算结果','viewer':manifest['viewer']}]
            recovered=[]
            if not manifest.get('study'):
                for binding in watch.get('caseViews',[]):
                    if binding['id'] not in {ref['id'] for ref in refs}:
                        recovered.append({k:binding[k] for k in ('id','label','viewer','caseRoot')})
                refs.extend(recovered)
            signature=[path.stat().st_mtime_ns,path.stat().st_size] if path.is_file() else []
            if watch:signature.extend(['workspaceWatch',watch_path.stat().st_mtime_ns,watch_path.stat().st_size])
            study=None;study_path=None
            if 'study' in manifest:
                from study import validate_study
                study_path=inside(work,manifest['study']);stamp=study_path.stat();signature.extend(['study',stamp.st_mtime_ns,stamp.st_size])
                # Observer bindings are an overlay; the solver keeps ownership
                # of its plan, responses, status, and selected default run.
                raw_study=read_json(study_path);raw_study=copy.deepcopy(raw_study)
                for binding in watch.get('caseBindings',[]):
                    run=next((r for r in raw_study.get('runs',[]) if r['id']==binding['runId']),None)
                    if run and not run.get('caseRoot'):run['caseRoot']=str(inside(work,binding['caseRoot']).relative_to(work))
                for run_id,binding in manifest.get('studyBindings',{}).items():
                    run=next((r for r in raw_study.get('runs',[]) if r['id']==run_id),None)
                    if not run or not run.get('caseRoot') or inside(work,run['caseRoot'])!=inside(work,binding['caseRoot']):raise ValueError('展示模型与参数组目录不一致')
                    run['viewIds']=list(dict.fromkeys([*run.get('viewIds',[]),*binding['viewIds']]))
                    run['defaultView']=binding['defaultView']
                    if binding.get('preview'):run['preview']=binding['preview']
                for binding in watch.get('models',[]):
                    run=next((r for r in raw_study.get('runs',[]) if r['id']==binding['runId']),None)
                    if not run or run['status'] in {'failed','skipped'} or not run.get('caseRoot') or inside(work,run['caseRoot'])!=inside(work,binding['caseRoot']):continue
                    explicit=[r for r in refs if r['id'] in run.get('viewIds',[]) and not r['id'].startswith('observed-')]
                    if any(read_json(inside(work,r['viewer'])).get('schema')=='mandifuel.viewer/v1' for r in explicit):continue
                    if binding['id'] not in {r['id'] for r in refs}:refs.append({k:binding[k] for k in ['id','label','viewer']})
                    run['viewIds']=[*run.get('viewIds',[]),binding['id']]
                    run['defaultView']=binding['id']
            resolved=[];seen=set()
            for ref in refs:
                key=ref['id']
                if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}',key) or key in seen:raise ValueError('视图标识无效')
                seen.add(key);viewer=inside(work,ref['viewer']);stamp=viewer.stat();signature.extend([key,stamp.st_mtime_ns,stamp.st_size]);resolved.append((key,ref,viewer))
            deliveries={}
            for category in ('inputs','files'):
                rows=[]
                for item in sorted(set(manifest.get(category,[]))|set(watch.get(category,[]))):
                    file=inside(work,item)
                    if file.is_file():
                        stamp=file.stat();relative=str(file.relative_to(work));rows.append({'path':relative,'name':file.name,'bytes':stamp.st_size,'modifiedNs':str(stamp.st_mtime_ns)});signature.extend([category,relative,stamp.st_mtime_ns,stamp.st_size])
                deliveries[category]=rows
            if signature==meta.get('handoffSignature'):
                meta.pop('importError',None)
                return
            if study_path is not None:study=validate_study(raw_study,[ref['id'] for ref in refs])
            views={}
            for key,ref,viewer in resolved:
                previous=job.get('views',{}).get(key,{})
                if bool(study)==('source' in previous) and (previous.get('source') or previous.get('viewer'))==str(viewer.relative_to(work)) and previous.get('stamp')==[viewer.stat().st_mtime_ns,viewer.stat().st_size]:views[key]={**previous,'label':str(ref.get('label','计算结果'))[:60]};continue
                bundle=validate_bundle(read_json(viewer));inside(work,bundle['caseRoot'])
                if ref in recovered and inside(work,bundle['caseRoot'])!=inside(work,ref['caseRoot']):
                    raise ValueError('保存场与恢复视图的计算目录不一致')
                if study:views[key]={'label':str(ref.get('label','计算结果'))[:60],'source':str(viewer.relative_to(work)),'schema':bundle['schema'],'task':bundle['task'],'caseRoot':bundle['caseRoot'],'stamp':[viewer.stat().st_mtime_ns,viewer.stat().st_size]}
                else:views[key]={'label':str(ref.get('label','计算结果'))[:60],'bundle':bundle,'viewer':str(viewer.relative_to(work)),'stamp':[viewer.stat().st_mtime_ns,viewer.stat().st_size]}
            if study:
                for run in study['runs']:
                    root=inside(work,run['caseRoot']) if 'caseRoot' in run else None
                    for ref in run['viewIds']:
                        if root is not None and inside(work,views[ref]['caseRoot'])!=root:raise ValueError('参数组与模型的计算目录不一致')
                        if run['status']=='queued' and views[ref]['schema']!='mandifuel.mesh/v1':raise ValueError('未执行组只能发布网格预览')
            preferred=manifest.get('defaultView',next(iter(views),'main'))
            if recovered and (preferred not in views or views[preferred].get('bundle',{}).get('schema')=='mandifuel.mesh/v1'):
                preferred=recovered[0]['id']
            if views and preferred not in views:raise ValueError('默认视图不存在')
            if not views and not any(deliveries.values()) and study is None and not any(k.startswith('saved-case-') for k in job.get('views',{})):
                # An empty observer index is normal while a new task prepares
                # inputs. Only an explicit empty handoff is an import error.
                if not path.is_file():
                    meta.pop('importError',None)
                    return
                raise ValueError('清单中没有模型或文件')
            if views and (views!=job.get('views') or preferred!=meta.get('defaultView')):
                job['views']=views;job['bundle']=views[preferred].get('bundle');atomic(work.parent/'views.json',views)
                if job['bundle']:atomic(work.parent/'bundle.json',job['bundle'])
                meta['modelVersion']=meta.get('modelVersion',0)+1;meta['defaultView']=preferred
                if any((v['bundle']['schema'] if 'bundle' in v else v['schema'])=='mandifuel.viewer/v1' for v in views.values()):meta['resultVersion']+=1
            elif not views and (study is not None or any(k.startswith('saved-case-') for k in job.get('views',{}))) and (job.get('views') or job.get('bundle')):
                job['views']={};job['bundle']=None;atomic(work.parent/'views.json',{});meta['modelVersion']=meta.get('modelVersion',0)+1
                (work.parent/'bundle.json').unlink(missing_ok=True)
            if study!=meta.get('study'):
                meta['study']=study;meta['studyVersion']=meta.get('studyVersion',0)+1
            if config is not None:
                from presentation import validate_delivery,requested_delivery
                if 'ui' in config:
                    from ui_policy import clean_document
                    config['ui'],_=clean_document(config['ui'])
                requirements=requested_delivery(latest_request(meta))
                if requirements:config['deliveryRequirements']={**config.get('deliveryRequirements',{}),**requirements}
                try:validate_delivery(config,{key:{'task':v['bundle']['task'] if 'bundle' in v else v['task']} for key,v in views.items()},preferred,meta.get('presentation',{}),work,study)
                except ValueError as error:presentation_error='显示配置未应用：'+str(error);config={}
                presentation=dict(meta.get('presentation',{}));signatures=meta.setdefault('manifestPresentationSignatures',{})
                from agent_panel import parameter_state
                panel_signature=hashlib.sha256(json.dumps([meta.get('promptRevision',0),{k:config[k] for k in ['controls','parameterValues'] if k in config}],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if signatures.get('agentParameterState')!=panel_signature:
                    values=parameter_state(presentation,config)
                    if values is not None:
                        config['parameterValues']=values;presentation['parameterRevision']=presentation.get('parameterRevision',0)+1
                    signatures['agentParameterState']=panel_signature
                elif 'parameterValues' in config:config['parameterValues']=copy.deepcopy(presentation.get('parameterValues',{}))
                for key,value in config.items():
                    digest=hashlib.sha256(json.dumps([meta.get('promptRevision',0),value],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                    if signatures.get(key)!=digest:
                        if key=='rendering':
                            from rendering import merge_rendering
                            value=merge_rendering(presentation.get('rendering'),value)
                            presentation['renderingRevision']=presentation.get('renderingRevision',0)+1
                        if key=='viewState':presentation['viewStateRevision']=presentation.get('viewStateRevision',0)+1
                        if key=='interactions':presentation['interactionRevision']=presentation.get('interactionRevision',0)+1
                        if key=='ui':presentation['uiRevision']=presentation.get('uiRevision',0)+1
                        presentation[key]=value;signatures[key]=digest
                if presentation!=meta.get('presentation'):meta['presentation']=presentation;meta['presentationVersion']=meta.get('presentationVersion',0)+1
            if any(meta.get(key,[])!=rows for key,rows in deliveries.items()):meta['deliveryVersion']=meta.get('deliveryVersion',0)+1
            meta['workspaceWatch']={k:watch[k] for k in ['revision','events','errors'] if k in watch}
            meta.update(deliveries);meta.update(handoffSignature=signature,importError=None,presentationError=presentation_error)
        except Exception as exc:meta['importError']='结果导入失败：'+str(exc)
    def _view_bundle(self,job,view=None):
        key=view if view is not None else job['meta'].get('defaultView')
        row=job.get('views',{}).get(key)
        if row is None:
            if view is not None:raise ValueError('此模型视图尚未交付')
            if job['bundle']:return job['bundle']
            raise ValueError('尚未交付此模型')
        if 'bundle' in row:return row['bundle']
        path=inside(job['workspace'],row['source']);stamp=path.stat()
        if [stamp.st_mtime_ns,stamp.st_size]!=row['stamp']:raise ValueError('模型更新尚未登记，请等待交付刷新')
        cache_key=(str(path),stamp.st_mtime_ns,stamp.st_size)
        if cache_key in self.view_cache:self.view_cache.move_to_end(cache_key);return self.view_cache[cache_key]
        bundle=validate_bundle(read_json(path));inside(job['workspace'],bundle['caseRoot'])
        if bundle['task']!=row['task']:raise ValueError('模型已更新，请等待交付重新登记')
        self.view_cache[cache_key]=bundle
        while len(self.view_cache)>3 or sum(k[2] for k in self.view_cache)>MAX_JSON:self.view_cache.popitem(last=False)
        return bundle
    def fields(self,ident,view=None):
        with self.lock:return copy.deepcopy(self._view_bundle(self._job(ident),view)['data'])
    def study(self,ident):
        with self.lock:
            value=self._job(ident)['meta'].get('study')
            if value is None:raise ValueError('尚未交付研究汇总')
            return copy.deepcopy(value)
    def progress(self,ident):
        with self.lock:
            meta=self._job(ident)['meta'];return {'rows':copy.deepcopy([row for row in meta.get('progressHistory',[]) if row.get('source')=='process-observer']),'complete':meta.get('progressHistoryComplete',False) and all(row.get('source')=='process-observer' for row in meta.get('progressHistory',[]))}
    def events(self,ident):
        with self.lock:return copy.deepcopy(self._job(ident)['meta'].get('events',[]))
    def file(self,ident,path):
        with self.lock:
            job=self._job(ident);allowed={f['path'] for f in job['meta'].get('inputs',[])+job['meta'].get('files',[])}
            if path not in allowed:raise ValueError('文件未登记在交付清单中')
            result=inside(job['workspace'],path)
            if not result.is_file() or result.stat().st_size>MAX_JSON:raise ValueError('文件不可用或超过大小限制')
            return result
    def updates(self,ident,after):
        with self.condition:
            job=self._job(ident)
            if after>=job['seq']:self.condition.wait(timeout=12)
            return [copy.deepcopy(e) for e in job['journal'] if e['id']>after]
    def close(self):
        self.evidence.close()
        self.process_monitor.close()
        self.dashboard.close()
        with self.condition:self.shutting_down=True;self.condition.notify_all()
