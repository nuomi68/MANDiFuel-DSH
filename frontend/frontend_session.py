"""Read models and revisioned transactions for the private frontend operator."""
import copy
import time
import secrets
import json
from adaptive_ui import CATALOG
from rendering import CAPABILITIES
from slot_protocol import SLOTS,frontend_revision,patch_slots,FrontendConflict


def snapshot(dashboard,ident,target='page',node_id=None):
    from registry import latest_request
    if target not in {'page','main','aside','settings','model','data','capabilities','evidence'}:raise ValueError('未知前端状态目标')
    r=dashboard.registry
    with r.lock:
        job=r._job(ident);m=job['meta'];public=r.public(job);p=copy.deepcopy(public.get('presentation',{}))
        observation=copy.deepcopy(m.get('uiState',{}));age=time.time()-m.get('uiObservedAt',0)
        result={'protocol':'mandifuel.frontend/v1','revision':frontend_revision(m),'task':{'id':ident,'title':m['title'],'status':m['status'],'request':latest_request(m)},'presentationVersion':m.get('presentationVersion',0),'uiRevision':p.get('uiRevision',0),'viewStateRevision':p.get('viewStateRevision',0),'interactionRevision':p.get('interactionRevision',0)}
        selected=next((v for v in public['views'] if v['id']==observation.get('selection',{}).get('view')),None) if age<20 else None
        result['modelRequirement']={'required':bool(public.get('modelReady')),'kind':('fields' if selected['kind']=='results' else 'mesh') if selected else ('fields' if public.get('resultReady') else 'mesh')}
        result['policy']={'scalarCards':False,'duplicateWindows':False,'progressOwner':'process-observer','physicalFieldWindow':'mesh first, saved fields next; collapse completed tasks without a model'}
        result['progress']=copy.deepcopy(public.get('progress',{}))
        result['evidenceSummary']=copy.deepcopy(public.get('evidence',{}))
        if target=='evidence':result.update(evidence=r.evidence.index(ident,node_id));return result
        if target=='page':
            document=p.get('ui') or {}
            result.update(slots=copy.deepcopy(SLOTS),protected=['application-shell','native-dsh','workflow-progress','evidence-browser'],browser={'connected':age<20,'ageSeconds':round(age,1) if m.get('uiObservedAt') else None,**observation},viewer=copy.deepcopy(m.get('viewerState',{})),parameters=p.get('parameterValues',{}),composition={slot:_summary(document.get(key)) for slot,key in [('main','root'),('aside','aside')]},settings=[{'id':c['id'],'label':c.get('label'),'type':c['type']} for c in p.get('controls',[])])
        elif target in {'main','aside'}:
            tree=(p.get('ui') or {}).get('root' if target=='main' else 'aside')
            if node_id:
                from slot_protocol import _find
                found=_find(tree,node_id)
                if not found:raise ValueError('插槽中不存在组件：'+node_id)
                tree=found[0]
            result.update(slot=target,tree=tree,documentOptions={k:v for k,v in (p.get('ui') or {}).items() if k not in {'root','aside'}},browserNodes=observation.get('nodes',[]))
        elif target=='settings':result.update(controls=p.get('controls',[]),values=p.get('parameterValues',{}),browser=observation.get('slots',{}).get('settings'))
        elif target=='model':result.update(views=public.get('views',[]),rendering=p.get('rendering',{}),viewState=p.get('viewState',{}),viewer=copy.deepcopy(m.get('viewerState',{})),actualDisplay=observation.get('display',{}),values=p.get('parameterValues',{}))
        elif target=='capabilities':result.update(slots=copy.deepcopy(SLOTS),components=CATALOG,rendering=CAPABILITIES,operations=['replace','insert','update','remove','move','upsert','interact'],limits={'operationsPerTransaction':24,'mutationsPerRun':8,'toolsPerRun':24},protected=['application-shell','native-dsh','solver-inputs','saved-fields'])
        elif target=='data':
            facts=dashboard.inspect(ident)
            groups=('availableTables','availableRecords','availableReports','availableImages')
            result['inspectHint']='Use ui_inspect(target="data", node="exact workspace-relative file") for its columns, units and samples; node="case:<caseRoot>" for a saved field catalog. This index avoids large tool results being offloaded to inaccessible files.'
            if node_id:
                if node_id.startswith('case:'):
                    result['cases']=[{k:c.get(k) for k in ('caseRoot','latestTime','fields','fieldCatalog','execution')} for c in facts['cases'] if c['caseRoot']==node_id[5:]]
                else:
                    for key in groups:result[key]=[row for row in facts.get(key,[]) if row['file']==node_id]
                    if not any(result.get(key) for key in groups):raise ValueError('没有登记该数据文件，请先读取 data 索引')
            else:
                result['cases']=[{'caseRoot':c['caseRoot'],'latestTime':c['latestTime'],'meshReady':c['meshReady'],'fieldCount':len(c['fields'])} for c in facts.get('cases',[])]
                result['views']=[{k:v.get(k) for k in ('id','label','kind','caseRoot')}|{'task':{k:v['task'].get(k) for k in ('shape','radius','timeUnit','fields')}} for v in facts.get('views',[])]
                result['availableTables']=[{'file':r['file'],'rows':r['rows'],'columns':[c['id'] for c in r['columns']]} for r in facts.get('availableTables',[])]
                result['availableRecords']=[{k:r.get(k) for k in ('file','rowsPath','count')} for r in facts.get('availableRecords',[])]
                result['availableReports']=[{'file':r['file'],'keys':list(r['metadata'])} for r in facts.get('availableReports',[])]
                result['availableImages']=facts.get('availableImages',[])
                for key in ('study','studyFile','studyRuns','workspaceHistory','deliveryRequirements'):result[key]=facts.get(key)
            result['evidence']=copy.deepcopy(public.get('evidence',{}))
    return result


def _summary(node):
    if not node:return None
    from ui_policy import content_key
    return {'id':node['id'],'type':node['type'],'contentKey':content_key(node),**({'text':node['text'][:300]} if node.get('text') else {}),**({'source':node['source']} if 'source' in node else {}),**({'title':node['title']} if 'title' in node else {}),**({'children':[_summary(c) for c in node['children']]} if 'children' in node else {})}


def apply(dashboard,ident,request):
    from registry import latest_request
    if not isinstance(request,dict) or not isinstance(request.get('update',{}),dict) or not isinstance(request.get('operations',[]),list) or any(not isinstance(op,dict) for op in request.get('operations',[])):raise ValueError('前端事务结构无效')
    update=request.get('update',{})
    if 'progress' in update:raise ValueError('标题流程进度由独立的 process-observer 维护，UI agent 不可写入')
    if update.get('exports') and ('ui' in update or any(op.get('slot') in {'main','aside'} for op in request.get('operations',[]))):raise ValueError('请先提交模型导出并检查字段，再提交引用它的组件树')
    r=dashboard.registry
    with r.lock:
        job=r._job(ident);revision=frontend_revision(job['meta'])
        if 'expectedRequest' in request and request['expectedRequest']!=latest_request(job['meta']):raise FrontendConflict('已有新的用户请求，旧操作会话不可继续提交')
        if request.get('expectedRevision')!=revision:raise FrontendConflict('前端状态已变化，请重新 ui_inspect 后提交；当前版本 '+revision)
        update,slots=patch_slots(r.public(job).get('presentation',{}),request)
        from ui_policy import clean_document
        removed=[]
        if 'ui' in update:update['ui'],removed=clean_document(update['ui'])
    published=dashboard.publish(ident,update,expected_frontend_revision=revision)
    if published.get('importError'):raise ValueError(published['importError'])
    with r.lock:
        m=r._job(ident)['meta']
        result={**published,'revision':frontend_revision(m),'changedSlots':slots,'cleanedPanels':removed,'renderStatus':'pending'}
    return result

def selection_check(registry,ident,request):
    """One live browser round trip. Never enqueue a test for a future visitor."""
    with registry.condition:
        job=registry._job(ident);meta=job['meta'];browser=meta.get('uiState',{})
        revision=meta.get('presentation',{}).get('uiRevision',0)
        if request.get('revision')!=frontend_revision(meta):raise FrontendConflict('页面选择已变化，请重新读取当前状态')
        if not browser.get('browserId') or time.time()-meta.get('uiObservedAt',0)>20:return {'status':'offline'}
        if job.get('selectionCheck'):return {'status':'busy'}
        nonce=secrets.token_hex(16)
        command={'browserId':browser['browserId'],'uiRevision':revision,'nonce':nonce,'expires':int((time.time()+25)*1000)}
        pending=job['selectionCheck']={'command':command}
        try:
            registry._emit(job,'selection-check',command)
            registry.condition.wait_for(lambda:'result' in pending or registry.shutting_down,timeout=25)
            return pending.get('result',{'status':'unconfirmed'})
        finally:job.pop('selectionCheck',None)


def selection_check_result(registry,ident,reply):
    with registry.condition:
        job=registry._job(ident);pending=job.get('selectionCheck')
        if not pending or any(reply.get(k)!=pending['command'][k] for k in ('nonce','browserId')):return {'accepted':False}
        result=reply.get('result')
        if not isinstance(result,dict) or len(json.dumps(result,allow_nan=False))>2048 or result.get('status') not in {
                'verified','failed','not-applicable','unavailable','interrupted'}:raise ValueError('联动检查回执无效')
        if result['status']=='verified' and (result.get('restored') is not True or not isinstance(result.get('before'),dict) or not isinstance(result.get('observed'),dict) or all(result['before'].get(k)==result['observed'].get(k) for k in ('view','run','time'))):raise ValueError('联动检查缺少切换及还原记录')
        pending['result']=result
        registry.condition.notify_all()
        return {'accepted':True}
