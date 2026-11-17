"""Read models and revisioned transactions for the private frontend operator."""
import copy
import time
from adaptive_ui import CATALOG
from rendering import CAPABILITIES
from slot_protocol import SLOTS,frontend_revision,patch_slots,FrontendConflict


def snapshot(dashboard,ident,target='page',node_id=None):
    from registry import latest_request
    if target not in {'page','main','aside','settings','model','data','capabilities'}:raise ValueError('未知前端状态目标')
    r=dashboard.registry
    with r.lock:
        job=r._job(ident);m=job['meta'];public=r.public(job);p=copy.deepcopy(public.get('presentation',{}))
        observation=copy.deepcopy(m.get('uiState',{}));age=time.time()-m.get('uiObservedAt',0)
        result={'protocol':'mandifuel.frontend/v1','revision':frontend_revision(m),'task':{'id':ident,'title':m['title'],'status':m['status'],'request':latest_request(m)},'presentationVersion':m.get('presentationVersion',0),'uiRevision':p.get('uiRevision',0),'viewStateRevision':p.get('viewStateRevision',0),'interactionRevision':p.get('interactionRevision',0)}
        result['modelRequirement']={'required':bool(public.get('modelReady')),'kind':'fields' if public.get('resultReady') else 'mesh'}
        result['policy']={'scalarCards':False,'duplicateWindows':False,'progressOwner':'process-observer','physicalFieldWindow':'always retained; mesh first, saved fields next'}
        result['progress']=copy.deepcopy(public.get('progress',{}))
        if target=='page':
            document=p.get('ui') or {}
            result.update(slots=copy.deepcopy(SLOTS),protected=['application-shell','native-dsh','workflow-progress'],browser={'connected':age<20,'ageSeconds':round(age,1) if m.get('uiObservedAt') else None,**observation},viewer=copy.deepcopy(m.get('viewerState',{})),parameters=p.get('parameterValues',{}),composition={slot:_summary(document.get(key)) for slot,key in [('main','root'),('aside','aside')]},settings=[{'id':c['id'],'label':c.get('label'),'type':c['type']} for c in p.get('controls',[])])
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
            for key in ('cases','fieldFacts','availableTables','availableRecords','availableReports','availableImages','views','study','studyFile','studyRuns','workspaceHistory','deliveryRequirements'):result[key]=facts.get(key)
            result['request']=facts['task']['latestRequest']
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
