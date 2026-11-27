"""Read native lifecycle and solver evidence independently of presentation."""
import json
import re
import threading
from pathlib import Path
from workspace_watch import discover_cases,local_file
from process_briefs import activity_topic, observe

STEPS=[('prepare','算例输入'),('mesh','可用网格'),('solve','物理求解'),('results','结果提取')]
TERMINAL={'completed','failed','stopped','interrupted'}


def process_event(meta,payload):
    kind=payload['kind']
    if kind not in {'prompt','status','assistant-note','tool','tool-end','turn','failure','subprocess'}:return
    state=meta.setdefault('processState',{})
    if kind=='prompt':
        state.clear()
        if meta.get('status')!='running':
            state.update(awaitingStart=True,awaitingStartRound=meta.get('promptRevision',0))
    elif kind in {'tool','turn','failure'} or kind=='status' and payload.get('status')=='running':
        state.pop('awaitingStart',None)
    elif kind=='subprocess':
        ident=str(payload.get('sessionId',''))[:100]
        if not ident:return
        children=state.setdefault('children',{})
        if ident not in children and len(children)>=32:children.pop(next(iter(children)))
        child=children.setdefault(ident,{'status':'running'})
        if payload.get('status') in {'running','completed','failed','stopped','interrupted'}:
            child['status']=payload['status']
    observe(meta,payload)
    meta['processProgress']=process_progress(meta)


def process_progress(meta):
    state=meta.get('processState',{})
    status=meta.get('status','queued')
    awaiting=state.get('awaitingStart') and state.get('awaitingStartRound')==meta.get('promptRevision',0)
    if awaiting and status!='running':status='queued'
    cases=state.get('cases',[])
    reporting=state.get('reporting',{})
    receipts=[c.get('execution',{}).get('status') for c in cases]
    solving=[c for c in cases if c.get('execution',{}).get('status')=='running']
    children=[{'label':f'计算子任务 {i}', 'status':c['status']} for i,c in enumerate(state.get('children',{}).values(),1)]
    active_children=sum(c['status']=='running' for c in children)
    total=reporting.get('total',0)
    detail=''
    if status in TERMINAL:
        detail={'completed':'任务已结束','failed':'任务失败','stopped':'任务已停止','interrupted':'任务已中断'}[status]
        if solving:detail=f'会话已结束，{len(solving)} 个求解回执仍为运行中'
        if 'failed' in receipts:detail+='，工作区有失败回执'
    elif total:
        detail=f"工作区求解完成 {reporting['solved']}/{total} · 结果提取 {reporting['collected']}/{total}"
        if solving:
            detail=f"研究记录 {reporting['solved']}/{total} 已求解 · {len(solving)} 个回执仍为运行中 · 结果提取 {reporting['collected']}/{total}"
        if reporting.get('failed'):detail+=f" · {reporting['failed']} 组提取失败"
    elif solving:
        current=solving[-1].get('solverTime')
        detail='求解器运行中'+(f' · t = {current:g}' if current is not None else '')
    elif any(c.get('savedFields') for c in cases):detail='工作区已有保存场'
    elif any(c.get('meshReady') for c in cases):detail='工作区已有网格'
    elif active_children:detail=f'{active_children} 个计算子任务进行中'
    elif status=='queued':detail='正在准备新请求' if awaiting else '等待执行'
    recent=state.get('recent',[])
    if status=='running' and recent and recent[-1]['kind']=='tool-error':
        detail='最近一次工具调用报错'
    brief=state.get('brief',{})
    topic=activity_topic(brief.get('topic')) if brief.get('status')==status else ''
    summary=' · '.join(part for part in (topic,detail) if part) or '正在处理请求'
    # Stage badges reflect filesystem/receipt evidence. A finished chat may never run a solver.
    stages=[]
    if cases or total:
        complete={'prepare':bool(cases) and all(c.get('inputsPresent') for c in cases),
                  'mesh':bool(cases) and all(c.get('meshReady') for c in cases),
                  'solve':not solving and (reporting.get('solved')==total if total else bool(cases) and all(s=='completed' for s in receipts)),
                  'results':bool(total) and reporting.get('collected')==total}
        for key,label in STEPS:
            stage='done' if complete[key] else 'pending'
            if key=='solve' and not complete[key]:
                if 'failed' in receipts:stage='error'
                elif solving:stage='active'
            if key=='results' and reporting.get('failed'):stage='error'
            stages.append({'id':key,'label':label,'status':stage})
    return {'summary':summary,'stages':stages,'source':'process-observer',
            'summaryOrigin':'llm' if topic else 'observed','subprocesses':children}


class ProcessMonitor:
    def __init__(self,registry):
        self.registry=registry;self.stop=threading.Event();self.signatures={};self.errors={};self.reporting_cache={};self.final_scans=set()
        self.thread=threading.Thread(target=self._run,name='workflow-progress-observer',daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.wait(1.5):
            with self.registry.lock:
                final_scans=self.final_scans.copy()
                self.final_scans.clear()
                jobs=[(j['meta']['id'],j['workspace']) for j in self.registry.jobs.values() if not j['meta'].get('draft') and (j['meta'].get('status') not in TERMINAL or j['meta']['id'] in final_scans or any(c.get('execution',{}).get('status')=='running' for c in j['meta'].get('processState',{}).get('cases',[])))]
            for ident,work in jobs:
                if self.stop.is_set():return
                try:self.scan(ident,work);self.errors.pop(ident,None)
                except (OSError,ValueError) as error:self.errors[ident]=str(error)[:300]
    def scan(self,ident,work=None):
        r=self.registry
        with r.lock:
            job=r._job(ident);work=Path(work or job['workspace']);round_=job['meta'].get('promptRevision',0)
        cases=[]
        for c in discover_cases(work):
            row={k:c[k] for k in ('caseRoot','meshReady','latestTime','execution')}
            row['savedFields']=bool(c['fields'])
            row['inputsPresent']=bool(c['inputs'])
            log=work/c['caseRoot']/'log.offbeat'
            if local_file(work,log):
                with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-32768));tail=stream.read(32768).decode('utf-8','replace')
                times=re.findall(r'^Time\s*=\s*([\d.eE+\-]+)',tail,re.M)
                if times:
                    value=float(times[-1])
                    if abs(value)<1e100:row['solverTime']=value
            cases.append(row)
        reporting={};history=work/'history.json'
        if local_file(work,history) and history.stat().st_size<=32*1024*1024:
            stamp=(history.stat().st_mtime_ns,history.stat().st_size);cached=self.reporting_cache.get(ident)
            if cached and cached[0]==stamp:reporting=cached[1]
            else:
                records=json.loads(history.read_text())
                if isinstance(records,list) and records and all(isinstance(row,dict) and isinstance(row.get('point'),dict) for row in records):
                    reporting={'total':len(records),'solved':sum(row.get('status')=='completed' for row in records),'collected':sum(row.get('reporting_status')=='completed' for row in records),'failed':sum(row.get('reporting_status')=='failed' for row in records)}
                self.reporting_cache[ident]=(stamp,reporting)
        signature=json.dumps([cases,reporting],sort_keys=True)
        if self.signatures.get(ident)==(round_,signature):return
        self.signatures[ident]=(round_,signature)
        with r.lock:
            job=r._job(ident);meta=job['meta']
            if meta.get('promptRevision',0)!=round_:return
            state=meta.setdefault('processState',{});state['cases']=cases;state['reporting']=reporting;next_=process_progress(meta)
            changed=meta.get('processProgress')!=next_
            meta['processProgress']=next_
            r._save(job)
            if changed:r._emit(job,'state',r.public(job))
    def snapshot(self):return {'owner':'process-observer','running':self.thread.is_alive() and not self.stop.is_set(),'errors':dict(self.errors)}
    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
