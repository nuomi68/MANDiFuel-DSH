"""Validated, task-owned presentation state and lightweight workspace observations."""
from pathlib import Path
from registry import latest_request
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
from rendering import validate_rendering,merge_rendering,show_scale_controls,CAPABILITIES,PALETTES
from agent_panel import validate_parameter,program_parameters,parameter_state,check_program_values,validate_view_state
from adaptive_ui import validate_ui,validate_ui_delivery,ui_parameters,load_dataset,CATALOG

CONTROL_SPECS={
 'cut':{'type':'toggle','label':'剖切模型','default':False},
 'cutAngle':{'type':'range','label':'剖切角度','min':0,'max':180,'step':5,'default':90},
 'mesh':{'type':'toggle','label':'网格线框','default':False},
 'scale':{'type':'select','label':'色标范围','options':[{'value':'fixed','label':'固定范围'},{'value':'frame','label':'当前帧范围'},{'value':'custom','label':'自定义当前变量'}],'default':'fixed'},
 'axialScale':{'type':'range','label':'轴向显示比例','min':0.08,'max':1,'step':0.01,'default':0.16},
 'view':{'type':'select','label':'模型显示方式'},
 'cameraView':{'type':'select','label':'观察方向','default':'auto','options':[{'value':'auto','label':'自动'},{'value':'xy','label':'XY 正视'},{'value':'xz','label':'XZ 正视'},{'value':'yz','label':'YZ 正视'}]},
 'displayMode':{'type':'select','label':'显示内容','options':[{'value':'surface','label':'外表面'},{'value':'slice','label':'内部切片'}],'default':'surface'},
 'sliceAxis':{'type':'select','label':'切面方向','options':[{'value':'x','label':'垂直 X'},{'value':'y','label':'垂直 Y'},{'value':'z','label':'垂直 Z'}],'default':'z'},
 'slicePosition':{'type':'range','label':'切面位置','min':0,'max':1,'step':0.01,'default':0.5},
 'aspectMode':{'type':'select','label':'二维坐标比例','options':[{'value':'physical','label':'保持几何比例'},{'value':'fit','label':'展开坐标（缩放显示）'}],'default':'physical'},
 'compare':{'type':'toggle','label':'双变量比较','default':False},
 'compareField':{'type':'select','label':'右侧变量'},
 'extrema':{'type':'toggle','label':'标注当前帧全域最大最小值','default':False},
 'scaleX':{'type':'number','label':'X 显示缩放','min':.01,'max':100,'step':.1,'default':1},
 'scaleY':{'type':'number','label':'Y 显示缩放','min':.01,'max':100,'step':.1,'default':1},
 'scaleZ':{'type':'number','label':'Z 显示缩放','min':.01,'max':100,'step':.1,'default':1},
 'palette':{'type':'select','label':'颜色映射','default':'coolwarm','options':[{'value':v,'label':n} for v,n in [('coolwarm','蓝白红'),('viridis','紫绿黄'),('inferno','黑紫橙黄'),('gray','灰度'),('rainbow','蓝青黄红')]]},
 'reversePalette':{'type':'toggle','label':'反转色带','default':False},
 'opacity':{'type':'range','label':'表面不透明度','min':.05,'max':1,'step':.05,'default':1},
 'background':{'type':'color','label':'背景颜色','default':'#f1f5fc'},
 'wireColor':{'type':'color','label':'线框颜色','default':'#3d6eb3'},
 'colorMin':{'type':'number','label':'当前变量色标下限','min':-1e300,'max':1e300,'step':1,'default':0},
 'colorMax':{'type':'number','label':'当前变量色标上限','min':-1e300,'max':1e300,'step':1,'default':1},
}

def text(value,limit=240):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('展示文本类型或长度无效')
    return value

def validate_presentation(update):
    if not isinstance(update,dict):raise ValueError('展示配置必须是对象')
    unknown=set(update)-{'ui','viewState','interactions','panelTitle','panelDescription','parameterValues','rendering','deliveryRequirements','progress','parameters','controls','exports','defaultView','study','studyMapping'}
    if unknown:raise ValueError('展示更新含未知属性，必须提交可执行配置：'+', '.join(sorted(unknown)))
    result={}
    if 'ui' in update:result['ui']=validate_ui(update['ui'])
    if 'viewState' in update:result['viewState']=validate_view_state(update['viewState'])
    if 'interactions' in update:
        from interaction_actions import validate_interactions
        validate_interactions(update['interactions']);result['interactions']=copy.deepcopy(update['interactions'])
    for key,limit in [('panelTitle',100),('panelDescription',500)]:
        if key in update:result[key]=text(update[key],limit)
    if 'parameterValues' in update:
        if not isinstance(update['parameterValues'],dict) or len(update['parameterValues'])>100:raise ValueError('参数值映射无效')
        result['parameterValues']=copy.deepcopy(update['parameterValues'])
    if 'rendering' in update:result['rendering']=validate_rendering(update['rendering'])
    if 'deliveryRequirements' in update:
        req=update['deliveryRequirements']
        if not isinstance(req,dict) or set(req)-{'reconstruction','axis','angle','extrema'}:raise ValueError('展示交付要求无效')
        if 'reconstruction' in req and req['reconstruction']!='axisymmetric-revolve':raise ValueError('未知重建要求')
        if 'axis' in req and req['axis'] not in {'x','y','z'}:raise ValueError('未知旋转轴')
        if 'angle' in req and (isinstance(req['angle'],bool) or not isinstance(req['angle'],(int,float)) or not math.isfinite(req['angle']) or not 0<req['angle']<=360):raise ValueError('重建角度无效')
        if 'extrema' in req and not isinstance(req['extrema'],bool):raise ValueError('极值标注要求无效')
        result['deliveryRequirements']=dict(req)
    if 'progress' in update:
        p=update['progress'];stages=p.get('stages',[])
        if not isinstance(stages,list) or len(stages)>12:raise ValueError('阶段列表无效')
        result['progress']={'summary':text(p.get('summary',''),160),'stages':[]}
        for s in stages:
            if s.get('status') not in {'pending','active','done','error'}:raise ValueError('阶段状态无效')
            result['progress']['stages'].append({'id':text(s['id'],50),'label':text(s['label'],32),'status':s['status']})
    if 'parameters' in update:
        sections=update['parameters']
        if not isinstance(sections,list) or len(sections)>30:raise ValueError('参数分组无效')
        result['parameters']=[]
        for section in sections:
            items=section.get('items',[])
            if not isinstance(items,list) or len(items)>100:raise ValueError('参数条目无效')
            result['parameters'].append({'title':text(section.get('title',''),60),'items':[{'label':text(i['label'],80),'value':text(str(i['value']),500),'unit':text(i.get('unit',''),60)} for i in items]})
    if 'controls' in update:
        controls=update['controls']
        if not isinstance(controls,list) or len(controls)>100:raise ValueError('显示选项列表无效')
        rows=[];seen=set();bound_parameters=program_parameters(result.get('rendering',{}).get('program'))|ui_parameters(result.get('ui'))
        for c in controls:
            ident=c['id']
            if not isinstance(ident,str) or ident in seen:raise ValueError('参数 ID 类型无效或重复')
            if ident not in CONTROL_SPECS or c.get('parameter') is True or ident in bound_parameters:
                definition={**CONTROL_SPECS.get(ident,{}),**c} if ident in bound_parameters else c
                rows.append(validate_parameter(definition));seen.add(ident);continue
            seen.add(ident);row=dict(CONTROL_SPECS[ident]);row['id']=ident
            if 'label' in c:row['label']=text(c['label'],60)
            if row['type'] in {'range','number'}:
                for k in ('min','max','step'):
                    if k in c:
                        v=c[k]
                        if not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v):raise ValueError('滑条范围无效')
                        row[k]=v
                if row['min']>=row['max'] or row['step']<=0:raise ValueError('滑条范围无效')
                bounds=(0,180) if ident=='cutAngle' else (0,1) if ident=='slicePosition' else (.05,1) if ident=='opacity' else (.01,100) if ident in {'scaleX','scaleY','scaleZ'} else (-1e300,1e300) if ident in {'colorMin','colorMax'} else (.08,1)
                if row['min']<bounds[0] or row['max']>bounds[1]:raise ValueError('滑条超过渲染器支持范围')
            if 'options' in c:
                if row['type']!='select' or not isinstance(c['options'],list):raise ValueError('下拉选项无效')
                row['options']=[{'value':text(o['value'],60),'label':text(o['label'],80)} for o in c['options']]
                if ident=='scale' and any(o['value'] not in {'fixed','frame','custom'} for o in row['options']):raise ValueError('不支持的色标模式')
                if ident=='palette' and any(o['value'] not in PALETTES for o in row['options']):raise ValueError('不支持的命名色带')
            if 'default' in c:
                value=c['default']
                if row['type']=='toggle' and not isinstance(value,bool):raise ValueError('开关默认值无效')
                if row['type'] in {'range','number'} and (not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not row['min']<=value<=row['max']):raise ValueError('默认值超出范围')
                if row['type']=='color' and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):raise ValueError('颜色须为 #RRGGBB')
                if row['type']=='select' and (not isinstance(value,str) or (ident!='view' and row.get('options') and value not in [o['value'] for o in row['options']])):raise ValueError('下拉默认值无效')
                row['default']=value
            rows.append(row)
        result['controls']=rows
    return result


def default_controls(task,views,rendering=None):
    # The panel is filled by the agent. Only navigation has a fallback; feature
    # parameters are never generated just because the renderer supports them.
    ids=['view','cameraView','mesh'] if len(views)>1 else ['cameraView','mesh']
    if task.get('fields'):ids.append('scale')
    return [dict(CONTROL_SPECS[i],id=i) for i in ids]


def validate_delivery(config, views, preferred, previous=None, workspace=None, study=None):
    """Validate real delivered capabilities before accepting a completion claim."""
    models=[v['task'] for v in views.values()]
    merged={**(previous or {}),**config}
    rendering=merge_rendering((previous or {}).get('rendering'),config.get('rendering',{}))
    for annotation in (rendering.get('program') or {}).get('annotations',[]):
        if set(annotation.get('views',[]))-views.keys():raise ValueError('标注引用尚未交付的模型视图')
    parameters={c['id']:c for c in merged.get('controls',[]) if c.get('parameter')}
    missing=program_parameters(rendering.get('program'))-parameters.keys()
    if missing:raise ValueError('显示程序引用未定义参数：'+', '.join(sorted(missing)))
    unused=parameters.keys()-(program_parameters(rendering.get('program'))|ui_parameters(merged.get('ui')))
    if models and unused:raise ValueError('参数尚未连接到显示程序：'+', '.join(sorted(unused)))
    for key,value in config.get('parameterValues',{}).items():
        if key not in parameters:raise ValueError('未定义参数：'+str(key)+'；基础显示项请使用 viewState 或控件 default，不要放入 parameterValues')
        validate_parameter({**parameters[key],'default':value})
    current_values=parameter_state(previous or {},config)
    if current_values is None:current_values={key:merged.get('parameterValues',{}).get(key,c['default']) for key,c in parameters.items()}
    active=views.get(preferred,{}).get('task',{});program=rendering.get('program') or {}
    validate_ui_delivery(merged.get('ui'),views,preferred,merged.get('controls',[]),workspace,study)
    if 'interactions' in config:
        from interaction_actions import validate_interactions
        validate_interactions(config['interactions'],merged.get('ui'),check_targets=True)
    checked=check_program_values(program,current_values,active.get('coordinateBounds')) or {};bound_options={**config.get('viewState',{}),**checked.get('options',{})}
    for key,value in config.get('viewState',{}).items():
        if key in checked.get('options',{}) and checked['options'][key]!=value:raise ValueError('一次性视图指令与参数联动冲突，请更新对应参数或移除绑定：'+key)
    if 'view' in config.get('viewState',{}) and config['viewState']['view'] not in views:raise ValueError('目标视图尚未交付')
    if rendering.get('program',{}):
        active=views.get(preferred,{}).get('task',{})
        if rendering['program'].get('vertex') and active and active.get('shape')!='mesh':raise ValueError('顶点显示程序需要原始网格或已交付的重建网格')
    actual_fields={f['id'] for m in models for f in m.get('fields',[])}
    if set(config.get('rendering',{}).get('fields',{}))-actual_fields:raise ValueError('字段渲染配置引用了尚未交付的变量')
    active_fields={f['id'] for f in active.get('fields',[])}
    if set(program.get('fields',{}))-active_fields:raise ValueError('字段显示绑定引用了当前视图不存在的变量')
    for key in ['field','compareField']:
        if key in bound_options and bound_options[key] not in active_fields:raise ValueError('显示选项引用了当前视图不存在的字段')
    if bound_options.get('compare') and len(active_fields)<2:raise ValueError('当前视图没有可比较的多个字段')
    if (bound_options.get('revolve') or 'revolveAngle' in bound_options) and not (active.get('shape')=='mesh' and (active.get('dimensionality')==2 or active.get('reconstruction',{}).get('sourceDimension')==2)):raise ValueError('旋转显示需要二维轴对称网格')
    if bound_options.get('displayMode')=='slice' and (active.get('shape')!='mesh' or active.get('supportsSlice') is False):raise ValueError('当前视图没有内部切片拓扑，请使用原始网格视图')
    if bound_options.get('extrema') and not active.get('supportsExtrema'):raise ValueError('极值标注需要真实单元中心，请重新导出已有结果')
    for annotation in program.get('annotations',[]):
        targets=[views[v]['task'] for v in annotation.get('views',[preferred]) if v in views]
        for target in targets:
            if target.get('shape') not in {'mesh','sphere','shell','rod'}:raise ValueError('坐标标注需要已交付的几何视图')
            if annotation['type']=='probe':
                fields={f['id'] for f in target.get('fields',[])}
                if not fields or not target.get('supportsExtrema'):raise ValueError('点值标注需要实际字段和原始单元中心，请重新导出已有结果')
                if annotation.get('field','selected')!='selected' and annotation['field'] not in fields:raise ValueError('点值标注字段不可用')
    for c in config.get('controls',[]):
        if c.get('parameter'):continue
        ident=c['id']
        if ident=='axialScale' and models and not any(m.get('shape')=='rod' for m in models):raise ValueError('轴向显示比例仅适用于棒形重建，不能把二维网格拉伸成旋转体')
        if ident=='extrema' and not any(m.get('supportsExtrema') for m in models):raise ValueError('极值标注需要带真实单元中心的结果，请重新导出已有结果')
        if ident in {'displayMode','sliceAxis','slicePosition'} and models and not any(m.get('shape')=='mesh' and m.get('supportsSlice') is not False for m in models):raise ValueError('此交付没有原始内部单元拓扑，不能配置内部切片')
    progress=config.get('progress',{})
    completed=any(s.get('status')=='done' and re.search(r'render|display|reconstruct|渲染|展示|重建|交付',s.get('id','')+' '+s.get('label',''),re.I) for s in progress.get('stages',[])) or bool(re.search(r'(渲染|重建|标注|展示|视图).*(完成|已交付|已可)|(完成|已交付).*(渲染|重建|标注|展示|视图)',progress.get('summary','')))
    if not completed:return
    if not models:raise ValueError('尚未交付模型，不能报告渲染完成')
    req=merged.get('deliveryRequirements',{})
    active=views.get(preferred,{}).get('task',{})
    if req.get('reconstruction'):
        reconstruction=active.get('reconstruction',{})
        if reconstruction.get('type')!=req['reconstruction']:raise ValueError('默认视图尚未交付轴对称旋转重建，切换相机不代表生成旋转体')
        if req.get('axis') and reconstruction.get('axis')!=req['axis']:raise ValueError('实际旋转轴不满足交付要求')
        if req.get('angle') and reconstruction.get('angle')!=req['angle']:raise ValueError('实际旋转展开角度不满足交付要求')
        if not any(m.get('shape')=='mesh' and not m.get('reconstruction') for m in models):raise ValueError('旋转重建必须同时保留原始网格视图')
    if req.get('extrema') and (not active.get('supportsExtrema') or not (bound_options.get('extrema') is True or any(c['id']=='extrema' and c.get('default') is True for c in merged.get('controls',[])))):raise ValueError('尚未开启有真实位置依据的极值标注，不能报告完成')


def requested_delivery(request):
    """Recognize explicit display requests; ambiguous geometry stays unspecified."""
    compact=re.sub(r'\s+','',request);req={}
    if re.search(r'(旋转|旋成|绕轴|重建|展开).*(3/4|四分之三|270)',compact):req.update(reconstruction='axisymmetric-revolve',angle=270)
    for clause in re.split(r'[，,。；;！？!?\n]',request):
        if not re.search(r'最大|最小|极值',clause):continue
        if re.search(r'不必|不用|无需|不要|不需要|关闭|取消|隐藏|去掉|不强制|不是必须|不是必需',clause):req['extrema']=False
        elif re.search(r'标注.*(最大|最小|极值)|(最大|最小|极值).*标注',clause):req['extrema']=True
    return req


def case_facts(work):
    cases=[]
    for base,dirs,files in os.walk(work,followlinks=False):
        rel=Path(base).relative_to(work)
        dirs[:]=[d for d in dirs if d not in {'delivery','.git','sources','source-case','reference-case','node_modules','__pycache__'} and not (Path(base)/d).is_symlink()]
        if len(rel.parts)>5:dirs[:]=[];continue
        if 'system' not in dirs or 'constant' not in dirs:continue
        case=Path(base)
        if not (case/'system/controlDict').is_file():continue
        mesh=case/'constant/polyMesh';ready=all((mesh/n).is_file() for n in ('points','faces','owner','neighbour'))
        times=[]
        for d in case.iterdir():
            if not d.is_dir() or d.is_symlink():continue
            try:v=float(d.name)
            except ValueError:continue
            if math.isfinite(v) and v>0:times.append((v,d))
        latest=max(times,key=lambda t:t[0])[1] if times else None
        fields=[];signature=[]
        if latest:
            for p in sorted(latest.iterdir()):
                if p.is_file() and not p.is_symlink() and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',p.name):
                    fields.append(p.name);s=p.stat();signature.append([p.name,s.st_mtime_ns,s.st_size])
        meshstamp=[]
        if ready:
            for name in ('points','faces','owner','neighbour'):
                s=(mesh/name).stat();meshstamp.append([s.st_size,s.st_mtime_ns])
        receipt={};receipt_path=case/'.mandifuel-execution.json'
        if receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.stat().st_size<=65536:
            try:
                raw=json.loads(receipt_path.read_text());receipt={k:raw[k] for k in ('status','exit_code','final_time','terminal_marker') if k in raw}
            except (ValueError,OSError):pass
        cases.append({'caseRoot':str(rel) or '.', 'meshReady':ready,'latestTime':latest.name if latest else None,'fields':fields,'signature':signature,'meshSignature':meshstamp,'execution':receipt})
        dirs[:]=[d for d in dirs if d not in {'system','constant','0'} and not re.fullmatch(r'[0-9.eE+-]+',d)]
        if len(cases)>=20:break
    return cases


class Dashboard:
    def health(self):
        current=getattr(self,'current_scan',None)
        return {'fileThreadAlive':self.thread.is_alive(),'current':{**current,'elapsed':round(time.monotonic()-current['started'],1)} if current else None,'fileErrors':dict(self.watch_errors),'models':self.artifacts.snapshot()}
    def __init__(self,registry):
        self.registry=registry;self.stop=threading.Event();self.previews={};self.field_cache={};self.preview_locks={};self.observations={};self.watch_errors={};from workspace_watch import WorkspaceWatcher;from artifact_queue import ArtifactQueue;self.watcher=WorkspaceWatcher();self.artifacts=ArtifactQueue(self.render_artifacts);self.thread=threading.Thread(target=self.poll,name='presentation-files',daemon=True);self.thread.start()
    def poll(self):
        while not self.stop.wait(1):
            live=[]
            with self.registry.lock:
                for job in list(self.registry.jobs.values()):
                    # A stopped/completed solve can receive new postprocessing
                    # deliveries. Watching files must not depend on agent state.
                    if job['meta'].get('draft'):continue
                    self.current_scan={'taskId':job['meta']['id'],'phase':'import','started':time.monotonic()}
                    before=(job['meta'].get('modelVersion',0),job['meta'].get('importError'),job['meta'].get('presentationVersion',0),job['meta'].get('deliveryVersion',0))
                    self.registry._import(job,missing_ok=True)
                    after=(job['meta'].get('modelVersion',0),job['meta'].get('importError'),job['meta'].get('presentationVersion',0),job['meta'].get('deliveryVersion',0))
                    if before!=after:self.registry._save(job);self.registry._emit(job,'state',self.registry.public(job))
                    live.append(job['meta']['id'])
            # File delivery and raw saved-output previews do not wait for the
            # presentation agent, a browser acknowledgement, or the final turn.
            for ident in live:
                try:
                    self.current_scan={'taskId':ident,'phase':'files','started':time.monotonic()}
                    observation=self.watch_files(ident,render=False)
                    self.watch_errors.pop(ident,None)
                    if observation:self.artifacts.submit(ident,priority=not self.registry.jobs[ident]['meta'].get('modelVersion'))
                except Exception as error:
                    self.watcher.accepted.pop(ident,None);self.watch_errors[ident]=str(error)[:500]
            self.current_scan=None
    def watch_files(self,ident,render=True):
        r=self.registry
        with r.lock:
            job=r._job(ident);work=job['workspace'];study=copy.deepcopy(job['meta'].get('study'));views=r.public(job).get('views',[]);title=job['meta']['title']
        observation=self.watcher.scan(ident,work,study)
        if observation is None:return
        self.observations[ident]=observation
        try:self.watcher.reconcile(work,observation,study,views,title,render_models=render)
        except Exception:
            self.watcher.accepted.pop(ident,None)
            raise
        with r.lock:
            job=r._job(ident);r._import(job,missing_ok=True);r._save(job);r._emit(job,'state',r.public(job))
        return observation

    def render_artifacts(self,ident):
        r=self.registry
        with r.lock:
            job=r._job(ident);work=job['workspace'];study=copy.deepcopy(job['meta'].get('study'));views=r.public(job).get('views',[]);title=job['meta']['title'];observation=self.observations.get(ident)
        if observation:self.watcher.reconcile(work,observation,study,views,title)
        with r.lock:
            job=r._job(ident);r._import(job,missing_ok=True);r._save(job);r._emit(job,'state',r.public(job))
        self.preview(ident)

    def preview(self,ident):
        with self.preview_locks.setdefault(ident,threading.Lock()):
            r=self.registry
            with r.lock:
                job=r._job(ident);meta=job['meta'];work=job['workspace'];views=r.public(job).get('views',[])
                if meta['status'] in {'queued','draft'} or meta.get('study') or (work/'delivery/study.json').exists():return
                if views and any(v['id'] not in {'mesh-preview','live-results'} for v in views):return
            cases=[c for c in case_facts(work) if c['meshReady']]
            # Group ownership cannot be inferred from directories. Multi-case
            # jobs must publish their study plan and cumulative run bindings.
            if len(cases)!=1:return
            case=cases[0];kind='results' if case['latestTime'] and case['fields'] else 'mesh'
            if kind=='mesh' and any(v['id']=='live-results' for v in views):return
            signature=json.dumps([case,kind],sort_keys=True)
            if self.previews.get(ident)==signature:return
            key='live-results' if kind=='results' else 'mesh-preview'
            previous=next((v for v in views if v['id']=='live-results'),None)
            if previous:
                with r.lock:saved=job.get('views',{}).get('live-results',{});stamp=saved.get('stamp',[])
                latest_change=max([row[1] for row in case['signature']+case.get('meshSignature',[])],default=0)
                if stamp and stamp[0]>=latest_change:
                    self.previews[ident]=signature;return
            selectors=[f.get('selector',f['id']) for f in previous['task']['fields']] if kind=='results' and previous else None
            spec={'id':key,'label':'已保存结果' if kind=='results' else '原始网格','caseRoot':case['caseRoot'],'kind':kind,'time':'latest'}
            if selectors:spec['fields']=selectors
            self.publish(ident,{'exports':[spec],'defaultView':key})
            self.previews[ident]=signature
    def inspect(self,ident):
        r=self.registry
        with r.lock:
            job=r._job(ident);m=copy.deepcopy(job['meta']);work=job['workspace'];task=r.public(job)
            current=m.get('viewerState',{});view=current.get('view') or task.get('defaultView');field_facts=[]
            cache_key=(ident,m.get('modelVersion',0),view,current.get('time'))
            try:
                if cache_key not in self.field_cache:
                    data=r.fields(ident,view);frames=data.get('frames',[])
                    frame=min(frames,key=lambda f:abs(f['time']-current['time'])) if frames and isinstance(current.get('time'),(int,float)) else frames[-1] if frames else {}
                    stats=[{'id':key,'time':frame['time'],'min':min(values),'max':max(values),'uniform':min(values)==max(values)} for key,values in frame.get('fields',{}).items() if values]
                    self.field_cache[cache_key]=stats
                    while len(self.field_cache)>32:self.field_cache.pop(next(iter(self.field_cache)))
                field_facts=self.field_cache[cache_key]
            except (ValueError,OSError,KeyError):pass
        cases=[] if m.get('study') else case_facts(work)
        from field_catalog import saved_field_catalog
        for case in cases[:8]:
            if case['latestTime']:case['fieldCatalog']=saved_field_catalog(work/case['caseRoot'],case['latestTime'],case['fields'])
        actions=[e['action'] for e in m.get('events',[])[-4:]]
        status=m['status'];stage='prepare';summary='正在准备计算'
        if any(c['meshReady'] for c in cases):stage='mesh';summary='网格已生成，正在准备求解'
        if any(c['latestTime'] for c in cases):stage='results';summary='已有计算输出，正在整理结果'
        if status=='completed':stage='complete';summary='本轮已结束，正在整理展示'
        if status in {'failed','stopped','interrupted'}:stage=status;summary={'failed':'本轮执行失败','stopped':'计算已停止','interrupted':'计算已中断'}[status]
        if status=='running' and any(re.search(r'求解|运行.*offbeat|solve|offbeat ',a,re.I) for a in actions) and stage not in {'results'}:stage='solve';summary='正在执行求解'
        if m.get('study') and status in {'queued','running','importing'}:
            counts=task['study']['counts'];done=counts['completed'];total=task['study']['total']
            stage='results' if done else 'solve' if counts['running'] else 'prepare'
            summary=f'已完成 {done}/{total} 组求解' if done else f'正在准备 {total} 组参数'
            if counts['failed']:summary+=f' · {counts["failed"]}组失败待处理'
        tables=[];record_files=[];reports=[]
        declared={spec['path'] for spec in m.get('files',[]) if Path(spec.get('path','')).suffix.lower() in {'.json','.csv'}}
        candidates=sorted(declared,key=lambda path:(path.startswith('cases/'),path))[:40]
        for path in candidates:
            spec={'path':path}
            try:
                table=load_dataset(work,{'file':spec['path']});categories={}
                for column in table['columns']:
                    key=column['id']
                    if not any(isinstance(row.get(key),str) for row in table['rows'][:2]):continue
                    values=[]
                    for row in table['rows']:
                        value=row.get(key)
                        if isinstance(value,str) and value not in values:values.append(value)
                        if len(values)>16:break
                    if len(values)<=16:categories[key]=values
                tables.append({'file':spec['path'],'columns':table['columns'],'rows':len(table['rows']),'sample':table['rows'][:2],'categories':categories})
            except (ValueError,OSError):
                try:
                    from registry import inside,read_json
                    file=inside(work,spec['path'])
                    if file.stat().st_size>2*1024*1024:continue
                    value=read_json(file);arrays=[('',value)] if isinstance(value,list) else [(key,rows) for key,rows in value.items() if isinstance(rows,list)] if isinstance(value,dict) else []
                    if isinstance(value,dict) and len(reports)<8:
                        metadata={}
                        for key,item in value.items():
                            if isinstance(item,list) and any(isinstance(x,dict) for x in item):continue
                            if len(json.dumps(item))<=1600 and len(json.dumps({**metadata,key:item}))<=6000:metadata[key]=item
                        if metadata:reports.append({'file':spec['path'],'metadata':metadata})
                    for rows_path,rows in arrays:
                        if not rows or not all(isinstance(row,dict) for row in rows[:2]):continue
                        # Scalar summaries often share records with thousands
                        # of profile points. Keep a bounded sample of useful
                        # fields instead of hiding the entire result table.
                        sample=[];omitted=set()
                        for row in rows[:2]:
                            preview={}
                            for key,item in row.items():
                                if len(json.dumps(item))>1600 or len(json.dumps(sample+[{**preview,key:item}]))>6000:omitted.add(key)
                                else:preview[key]=item
                            sample.append(preview)
                        context={}
                        if isinstance(value,dict):
                            for key,item in value.items():
                                if key==rows_path or isinstance(item,list) and any(isinstance(x,dict) for x in item):continue
                                if len(json.dumps(item))<=1600 and len(json.dumps({**context,key:item}))<=4000:context[key]=item
                        record_files.append({'file':spec['path'],'rowsPath':rows_path,'count':len(rows),'sample':sample,'context':context,**({'omittedFields':sorted(omitted)} if omitted else {})})
                except (ValueError,OSError):continue
        observed={'studyVersion':m.get('studyVersion',0),'status':status,'stage':stage,'cases':cases,'promptRevision':m.get('promptRevision',0),'displayPromptRevision':m.get('displayPromptRevision',0),'workspaceRevision':m.get('workspaceWatch',{}).get('revision',0),'evidenceRevision':m.get('evidence',{}).get('revision')}
        data_revision=hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest()[:20]
        ui_state=m.get('uiState',{})
        if ui_state.get('revision')==m.get('presentation',{}).get('uiRevision',0) and ui_state.get('errors'):observed['uiErrors']=ui_state['errors']
        if m.get('viewerState',{}).get('rendererError'):observed['rendererError']=m['viewerState']['rendererError']
        revision=hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest()[:20]
        visible_views=task.get('views',[])
        if m.get('study'):visible_views=sorted(visible_views,key=lambda v:(v['id']!=view,v['id']!=task.get('defaultView')))[:2]
        from workspace_watch import history_facts
        workspace_history=history_facts(work,m.get('workspaceWatch',{}).get('events',[]))
        images=[]
        for base,dirs,names in os.walk(work,followlinks=False):
            rel=Path(base).relative_to(work);dirs[:]=[d for d in dirs if d not in {'cases','source-case','sources','.git','node_modules','__pycache__'} and not (Path(base)/d).is_symlink()] if len(rel.parts)<3 else []
            for name in sorted(names):
                p=Path(base)/name
                if len(images)<12 and p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} and not p.is_symlink() and 0<p.stat().st_size<=10*1024*1024:images.append({'file':str(p.relative_to(work)),'bytes':p.stat().st_size})
        return {'observer':self.health(),'workspaceHistory':workspace_history,'revision':revision,'dataRevision':data_revision,'presenter':m.get('presenter',{}),'task':{'title':m['title'],'request':m['prompt'],'latestRequest':latest_request(m),'displayOnly':bool(m.get('latestDisplayPrompt')),'status':status},'stage':stage,'summary':summary,'recentActions':actions,'cases':cases,'presentation':m.get('presentation',{}),'viewerState':m.get('viewerState',{}),'fieldFacts':field_facts,'deliveryRequirements':requested_delivery(latest_request(m)),'study':task.get('study'),'studyFile':'delivery/study.json' if (work/'delivery/study.json').is_file() else None,'studyVariables':{'parameters':m['study']['parameters'],'responses':m['study']['responses']} if m.get('study') else None,'viewCount':len(task.get('views',[])),'views':visible_views,'capabilities':list(CONTROL_SPECS),'renderingCapabilities':CAPABILITIES,'uiCapabilities':CATALOG,'uiState':m.get('uiState',{}),'deliveryFiles':m.get('files',[])[:40],'availableTables':tables,'availableReports':reports,'availableImages':images,'availableRecords':record_files[:8],'workspaceChanges':m.get('workspaceWatch',{}),'studyRuns':[run for run in m.get('study',{}).get('runs',[]) if run.get('caseRoot')][:20]}
    def publish(self,ident,update,*,expected_frontend_revision=None):
        # Export only existing case data. No shell or solver capability is provided.
        r=self.registry;config=validate_presentation(update)
        if 'ui' in config:
            from ui_policy import clean_document
            config['ui'],_=clean_document(config['ui'])
            from adaptive_ui import walk_ui
            requested={i for node in walk_ui(config['ui']) for i in node.get('evidence',[])+node.get('claims',[])}
            if requested:
                known={q['id'] for q in r.evidence.index(ident)['claims']}
                if requested-known:raise ValueError('引用了当前任务不存在的核查结论；请先 ui_inspect(target="evidence")')
        with r.lock:job=r._job(ident);work=job['workspace'];title=job['meta']['title']
        if config.get('progress'):
            req=requested_delivery(latest_request(job['meta']))
            if req:config['deliveryRequirements']={**config.get('deliveryRequirements',{}),**req}
        if 'studyMapping' in update:
            from workspace_watch import mapped_history_study
            from registry import atomic
            mapped_history_study(work,update['studyMapping'])
            mapping_path=work/'delivery/observed/study-map.json';mapping_path.parent.mkdir(parents=True,exist_ok=True);atomic(mapping_path,update['studyMapping'])
            self.watcher.accepted.pop(ident,None)
        exports=update.get('exports',[])
        if not isinstance(exports,list) or len(exports)>5:raise ValueError('模型交付列表无效')
        outputs=[];pending=[];candidate={v['id']:v for v in r.public(job).get('views',[])}
        if exports:
            if job['meta'].get('study'):
                for spec in exports:
                    run=next((row for row in job['meta']['study']['runs'] if row['id']==spec.get('runId')),None)
                    if not run or not run.get('caseRoot') or (work/run['caseRoot']).resolve()!=(work/spec['caseRoot']).resolve():raise ValueError('研究模型导出需要明确的 runId 和一致的 caseRoot')
                    if run['status'] in {'failed','skipped'} or run['status']=='queued' and spec['kind']!='mesh':raise ValueError('当前参数组状态不允许发布结果场')
            from export_case import export_case,export_mesh
            from registry import inside,read_json,validate_bundle
            for spec in exports:
                key=spec['id']
                if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,49}',key):raise ValueError('视图标识无效')
                case=inside(work,spec['caseRoot'])
                if not (case/'system/controlDict').is_file():raise ValueError('计算根目录无效')
                final=work/'delivery/views'/f'{key}.json';target=final.with_suffix('.next.json')
                if spec.get('kind')=='mesh':export_mesh(case,target,title=title,write_handoff=False)
                elif spec.get('kind')=='results':
                    # Never promote initial conditions to solved results.
                    facts=next((c for c in case_facts(work) if (work/c['caseRoot']).resolve()==case),None)
                    if not facts or not facts['latestTime']:raise ValueError('尚无已保存的计算结果')
                    export_case(case,target,title=title,selectors=spec.get('fields'),time=spec.get('time','latest'),shape=spec.get('shape','mesh'),radius=spec.get('radius'),inner_radius=spec.get('innerRadius',0),length=spec.get('length'),time_unit=spec.get('timeUnit'),radial_bands=spec.get('radialBands'),axis=spec.get('axis','z'),sweep_angle=spec.get('sweepAngle',270.),write_handoff=False)
                else:raise ValueError('未知交付类型')
                bundle=validate_bundle(read_json(target));pending.append((target,final));candidate[key]={'task':bundle['task']}
                outputs.append({'id':key,**({'runId':spec['runId']} if spec.get('runId') else {}),'label':text(spec.get('label','网格预览' if spec['kind']=='mesh' else '计算结果'),60),'viewer':str(final.relative_to(work))})
        with r.lock:
            job=r._job(ident);m=job['meta']
            if expected_frontend_revision is not None:
                from slot_protocol import frontend_revision,FrontendConflict
                if frontend_revision(m)!=expected_frontend_revision:raise FrontendConflict('前端状态已变化，旧事务未提交；请重新读取状态')
            if 'ui' not in config and m.get('presentation',{}).get('ui'):
                from ui_policy import clean_document
                cleaned,removed=clean_document(m['presentation']['ui'])
                if removed:config['ui']=cleaned
            preferred=config.get('viewState',{}).get('view') or update.get('defaultView') or (outputs[-1]['id'] if outputs else m.get('viewerState',{}).get('view')) or m.get('defaultView')
            if preferred not in candidate and 'view' not in config.get('viewState',{}):preferred=m.get('defaultView')
            validate_delivery(config,candidate,preferred,m.get('presentation',{}),work,m.get('study'))
            for target,final in pending:target.replace(final)
            if outputs or 'defaultView' in update or 'study' in update or config.get('ui',{} ) and config['ui'].get('datasets'):
                from registry import atomic,read_json
                manifest_path=work/'delivery/workbench.json'
                manifest_path.parent.mkdir(parents=True,exist_ok=True)
                manifest=read_json(manifest_path) if manifest_path.exists() else {'schema':'mandifuel.handoff/v1'}
                if config.get('ui'):
                    manifest['files']=sorted(set(manifest.get('files',[]))|{spec['file'] for spec in config['ui'].get('datasets',{}).values()})
                views={}
                from registry import inside,validate_bundle
                for v in manifest.get('views',[]):
                    try:validate_bundle(read_json(inside(work,v['viewer'])));views[v['id']]=v
                    except (ValueError,KeyError,OSError):continue
                if not views and manifest.get('viewer'):
                    key=m.get('defaultView','main');views[key]={'id':key,'label':'已有结果','viewer':manifest['viewer']}
                for spec,output in zip(exports,outputs):
                    if spec.get('runId'):
                        bindings=manifest.setdefault('studyBindings',{});old=bindings.get(spec['runId'],{})
                        bindings[spec['runId']]={'caseRoot':spec['caseRoot'],'viewIds':list(dict.fromkeys([*old.get('viewIds',[]),output['id']])),'defaultView':output['id']}
                        if spec.get('fields'):bindings[spec['runId']]['preview']={'fields':spec['fields'],'time':spec.get('time','latest')}
                views.update({v['id']:{k:value for k,value in v.items() if k!='runId'} for v in outputs});manifest['views']=list(views.values())
                preferred=update['defaultView'] if 'defaultView' in update else outputs[-1]['id'] if outputs else manifest.get('defaultView',next(iter(views),None))
                if views and preferred not in views:raise ValueError('默认视图未交付')
                if views:manifest['defaultView']=preferred
                if 'study' in update:
                    study_path=inside(work,update['study']);manifest['study']=str(study_path.relative_to(work))
                manifest.pop('viewer',None)
                if not manifest.get('inputs'):
                    inputs=[]
                    for spec in exports:
                        case=(work/spec['caseRoot']).resolve()
                        for directory in ('0','constant','system'):
                            for p in (case/directory).rglob('*'):
                                if p.is_file() and not p.is_symlink() and 'polyMesh' not in p.parts:inputs.append(str(p.relative_to(work)))
                    manifest['inputs']=sorted(set(inputs))
                atomic(manifest_path,manifest);r._import(job,missing_ok=True)
            presentation=dict(m.get('presentation',{}))
            if 'ui' in config:presentation['uiRevision']=presentation.get('uiRevision',0)+1
            if 'viewState' in config:presentation['viewStateRevision']=presentation.get('viewStateRevision',0)+1
            if 'interactions' in config:presentation['interactionRevision']=presentation.get('interactionRevision',0)+1
            values=parameter_state(presentation,config)
            if values is not None:
                config['parameterValues']=values;presentation['parameterRevision']=presentation.get('parameterRevision',0)+1
            if 'rendering' in config:
                config['rendering']=merge_rendering(presentation.get('rendering'),config['rendering'])
                presentation['renderingRevision']=presentation.get('renderingRevision',0)+1
            presentation.update(config)
            if presentation!=m.get('presentation',{}):m['presentation']=presentation;m['presentationVersion']=m.get('presentationVersion',0)+1
            r._save(job);r._emit(job,'state',r.public(job))
            return {'published':True,'modelReady':r.public(job)['modelReady'],'presentationVersion':m.get('presentationVersion',0),'uiRevision':presentation.get('uiRevision',0),'viewStateRevision':presentation.get('viewStateRevision',0),'interactionRevision':presentation.get('interactionRevision',0),'importError':m.get('importError')}
    def parameter_values(self,ident,values):
        if not isinstance(values,dict) or len(values)>100:raise ValueError('参数值映射无效')
        r=self.registry
        with r.lock:
            job=r._job(ident);presentation=job['meta'].setdefault('presentation',{})
            validate_delivery({'parameterValues':values},{v['id']:v for v in r.public(job).get('views',[])},job['meta'].get('viewerState',{}).get('view') or job['meta'].get('defaultView'),presentation,job['workspace'],job['meta'].get('study'))
            next_values=parameter_state(presentation,{'parameterValues':values})
            presentation['parameterValues']=next_values;r._save(job)
            # Interactions are observations, not new agent requests or stages.
            return {'parameterValues':next_values}
    def viewer_state(self,ident,state):
        if not isinstance(state,dict) or set(state)-{'view','field','compareField','time','cameraView','displayMode','sliceAxis','slicePosition','compare','revolve','revolveAngle','camera','rendererError','revision'}:raise ValueError('视图观察无效')
        clean=validate_view_state({k:v for k,v in state.items() if k not in {'camera','rendererError','revision'}})
        if 'revision' in state:
            if type(state['revision']) is not int or state['revision']<0:raise ValueError('视图观察版本无效')
            clean['revision']=state['revision']
        if 'rendererError' in state:clean['rendererError']=text(state['rendererError'],500)
        if 'camera' in state:
            camera=state['camera']
            if not isinstance(camera,dict) or set(camera)-{'yaw','tilt','zoom','panX','panY'} or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in camera.values()):raise ValueError('相机观察无效')
            clean['camera']=dict(camera)
        r=self.registry
        with r.lock:
            job=r._job(ident)
            if 'revision' in clean and clean['revision']!=job['meta'].get('presentation',{}).get('viewStateRevision',0):return {'observed':False,'stale':True}
            if clean.get('view') not in job.get('views',{}):raise ValueError('观察视图尚未交付')
            if clean!=job['meta'].get('viewerState'):job['meta']['viewerState']=clean;r._save(job)
        return {'observed':True}
    def ui_dataset(self,ident,dataset,revision=None):
        r=self.registry
        with r.lock:
            job=r._job(ident);spec=(job['meta'].get('presentation',{}).get('ui') or {}).get('datasets',{}).get(dataset)
            if revision is not None and revision!=job['meta'].get('presentation',{}).get('uiRevision',0):raise ValueError('展示数据版本已变化，请等待刷新')
            if spec is None:raise ValueError('展示数据表尚未声明')
            return load_dataset(job['workspace'],spec)
    def ui_image(self,ident,relative):
        from adaptive_ui import walk_ui,image_file
        r=self.registry
        with r.lock:
            job=r._job(ident);document=job['meta'].get('presentation',{}).get('ui')
            if not any(n['type']=='image' and n['file']==relative for n in walk_ui(document)):raise ValueError('展示图片尚未声明')
            return image_file(job['workspace'],relative)
    def ui_state(self,ident,state):
        if not isinstance(state,dict) or set(state)-{'revision','presentationVersion','interactionRevision','ready','panels','errors','viewport','slots','nodes','selection','parameters','display','model','pickedPoint','browserId'} or type(state.get('revision')) is not int:raise ValueError('界面观察无效')
        if not isinstance(state.get('panels',[]),list) or len(state.get('panels',[]))>64 or not all(isinstance(v,str) and len(v)<=100 for v in state.get('panels',[])):raise ValueError('面板观察无效')
        errors=state.get('errors',[])
        if not isinstance(errors,list) or len(errors)>64 or any(not isinstance(e,dict) or set(e)!={'id','message'} or not isinstance(e['id'],str) or len(e['id'])>100 or not isinstance(e['message'],str) or len(e['message'])>500 for e in errors):raise ValueError('界面错误观察无效')
        from frontend_observation import validate_observation
        validate_observation(state)
        r=self.registry
        with r.lock:
            job=r._job(ident)
            if state['revision']!=job['meta'].get('presentation',{}).get('uiRevision',0):return {'observed':False,'stale':True}
            if 'presentationVersion' in state and state['presentationVersion']!=job['meta'].get('presentationVersion',0):return {'observed':False,'stale':True}
            job['meta']['uiObservedAt']=time.time()
            if state!=job['meta'].get('uiState'):job['meta']['uiState']=copy.deepcopy(state);r._save(job)
        return {'observed':True}
    def close(self):self.stop.set();self.thread.join(timeout=3);self.artifacts.close()
