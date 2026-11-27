"""Thin task-scoped HTTP adapter for the same application runtime used by the CLI."""
from pathlib import Path
import re
import sys
from threading import Lock
from time import monotonic

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from mandifuel_app.runtime import Application
from mandifuel_app.runtime import read

_observations = {}
_lock = Lock()



def build(manager, ident, body):
    """A task may opt in before it has a case. Claim a verified result exactly once."""
    action, nonce = body.get('action'), body.get('requestId')
    if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{32}',nonce):
        raise ValueError('缺少有效的计算器构建标识')
    with manager.lock:
        job = manager._job(ident)
        mutex = job.setdefault('calculatorLock', Lock())

    def update(record):
        with manager.lock:
            job['meta']['calculatorRequest'] = record
            manager._save(job)
            manager._emit(job,'state',manager.public(job))
        return record

    with mutex:
        with manager.lock:
            current = dict(job['meta'].get('calculatorRequest',{'state':'off'}))
            status = job['meta']['status']
        state = current['state']
        if action=='schedule':
            if state in {'waiting','building'} or current.get('requestId')==nonce:return current
            prompt,view = body.get('request'),body.get('view')
            if not isinstance(prompt,str) or not 0<len(prompt.strip())<=3000:
                raise ValueError('请提供 1–3000 字的构建要求')
            if view is not None and not isinstance(view,str):raise ValueError('结果视图无效')
            if status in {'failed','interrupted','stopped'}:raise ValueError('任务尚未成功完成')
            return update(dict(state='waiting',requestId=nonce,request=prompt.strip(),view=view))
        if current.get('requestId')!=nonce:return current
        if action=='cancel':
            if state in {'waiting','building'}:return update(dict(state='off',requestId=nonce))
            return current
        if action=='claim' and state=='waiting':
            if status in {'failed','interrupted','stopped'}:
                return update(dict(current,state='error',message='本次计算已停止或未成功完成'))
            if status!='completed':return current
            with manager.lock:
                task = manager.public(job)
                task_prompt = job['meta']['prompt']
            views = [v for v in task['views'] if v.get('kind')=='results' and v.get('caseRoot')]
            if current.get('view'):
                views = [v for v in views if v['id']==current['view']]
            else:
                views.sort(key=lambda v:v['id']!=task['defaultView'])
            if not views:return current
            reason = ''
            for view in views:
                app = application(manager,ident,view['caseRoot'])
                chosen = dict(current,view=view['id'],case=view['caseRoot'])
                if app.spec.is_file():return update(dict(chosen,state='ready'))
                try:capabilities = app.capabilities()
                except (ValueError,OSError) as error:
                    reason = reason or str(error)
                    continue
                with manager.lock:
                    if job['meta']['status']!='completed':return current
                    record = update(dict(chosen,state='building'))
                return dict(record,claimed=True,capabilities=capabilities,taskRequest=task_prompt,sessionId=task['nativeSessionId'])
            return update(dict(current,state='error',message=reason or '当前保存工况没有可执行的应用绑定'))
        if state!='building':return current
        if action=='fail':return update(dict(current,state='error',message=str(body.get('message') or '构建失败')[:350]))
        if action=='publish':
            definition = body.get('definition')
            if not isinstance(definition,dict):
                raise ValueError('构建助手需要提交完整的应用定义')
            components = definition.get('components',[])
            shown = [c.get('output') for c in components if isinstance(c,dict)] if isinstance(components,list) else []
            outputs = definition.get('outputs',[])
            if isinstance(outputs,list):
                missing = [str(o.get('id')) for o in outputs if isinstance(o,dict) and o.get('kind')!='field' and o.get('id') not in shown]
                if missing:raise ValueError('请为这些应用输出绑定图表或表格：'+', '.join(missing))
            application(manager,ident,current['case']).create(definition)
            return update(dict(current,state='ready'))
        return current


def observed(app):
    with _lock:
        ts, state = _observations.get(app.root,(0,{}))
    return state if monotonic()-ts<12 else {'connected':False}


def application(manager, ident, case):
    if not isinstance(case,str) or not case:
        raise ValueError('请指定任务中的算例')
    workspace = manager._job(ident)['workspace']
    return Application(workspace,case,workspace.parent/'applications')


def published_views(workspace,views):
    """List saved field views with a published contract in this task."""
    store=workspace.parent/'applications'
    if not store.is_dir():return []
    matches=[]
    for view in views:
        case=view.get('caseRoot')
        if view.get('kind')=='results' and case and Application(workspace,case,store).spec.is_file():
            matches.append({'case':case,'view':view['id']})
    return matches


def get(manager, ident, query):
    def arg(name):
        return query.get(name,[None])[0]
    app = application(manager,ident,arg('case'))
    if not app.spec.is_file() and 'candidate' in query:
        raise ValueError('当前算例没有已发布的计算器')
    if not app.spec.is_file():
        with manager.lock:
            record = manager._job(ident)['meta'].get('calculatorRequest',{})
            build_info = {k:record[k] for k in ('state','message','requestId') if k in record} if record.get('case')==app.relative else {'state':'off'}
        return {'spec':None,'runs':[], 'build':build_info, **(app.availability() if arg('inspect') else {})}
    if 'candidate' in query:
        return app.candidate(arg('candidate'))
    if arg('inspect'):
        with manager.lock:
            views=manager.public(manager._job(ident)).get('views',[])
        return {**app.state(),'browser':observed(app),'views':[v['id'] for v in views if v.get('kind')=='results' and v.get('caseRoot')==app.relative]}
    if arg('artifact'):
        return app.artifact(arg('run'),arg('artifact'))
    if arg('output'):
        return app.table(arg('output'),query.get('run',[]))
    return app.state()


def post(manager, ident, body):
    app = application(manager,ident,body.get('case'))
    action = body.get('action')
    if action=='run':
        return app.run(body.get('version'),body.get('requestId'),body.get('values'),body.get('candidate'))
    if action=='components':
        from registry import latest_request
        with manager.lock:
            if 'expectedRequest' in body and body['expectedRequest']!=latest_request(manager._job(ident)['meta']):
                raise ValueError('已有新的展示请求，请重新读取应用')
            return app.evolve(body.get('version'),components=body.get('components'))
    if action=='observed':
        from mandifuel_app.runtime import read
        spec = read(app.spec)
        if body.get('version')!=spec['version']:
            return {'accepted':False}
        run = body.get('run')
        if not isinstance(run,str) or not re.fullmatch('baseline|[a-f0-9]{32}',run):
            raise ValueError('浏览器选中的工况无效')
        if read(app.root/'runs'/run/'record.json')['status']!='completed':
            raise ValueError('浏览器回执需要一个已完成工况')
        state = {k:body.get(k) for k in ('version','run')}
        values = body.get('draftValues')
        if isinstance(values,dict) and set(values)=={p['id'] for p in spec['parameters']}:
            state['draftValues']={k:str(v)[:64] for k,v in values.items()}
        if isinstance(body.get('candidate'),str):
            state['candidate']=body['candidate'][:400]
        state['canRun']=body.get('canRun') is True
        state.update(connected=True,ready=body.get('ready') is True,field=body.get('field') is True,components=[v for v in body.get('components',[]) if isinstance(v,str)][:16])
        with _lock:
            _observations[app.root]=(monotonic(),state)
        return {'accepted':True}
    raise ValueError('未知计算器操作')
