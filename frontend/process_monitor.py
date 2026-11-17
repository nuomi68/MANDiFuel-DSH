"""Independent read-only workflow lane, driven by native events and solver facts."""
import copy
import json
import re
import threading
from pathlib import Path
from workspace_watch import discover_cases,local_file

STEPS=[('prepare','输入准备'),('mesh','网格生成'),('solve','物理求解'),('results','结果提取')]
TERMINAL={'completed','failed','stopped','interrupted'}


def process_event(meta,payload):
    kind=payload['kind']
    if kind not in {'prompt','status','tool','tool-end','turn','failure','subprocess'}:return
    state=meta.setdefault('processState',{'phase':'prepare','children':{}})
    if kind=='prompt':
        state.clear();state.update(phase='prepare',children={},summary='正在准备新请求')
        if meta.get('status')!='running':state.update(awaitingStart=True,awaitingStartRound=meta.get('promptRevision',0))
    elif kind=='status' and payload.get('status')=='running':state.pop('awaitingStart',None)
    elif kind=='failure':state.update(phase='prepare',summary='任务启动失败')
    elif kind=='turn':state.pop('awaitingStart',None)
    elif kind=='tool':
        state.pop('awaitingStart',None)
        action=str(payload.get('action',''))[:180]
        phase='mesh' if re.search(r'生成网格|建立网格|blockMesh|网格划分',action,re.I) else 'solve' if re.search(r'启动.*求解|运行.*offbeat|执行.*计算|运行.*求解',action,re.I) else 'results' if re.search(r'提取|后处理|校核|汇总|报告',action) else state.get('phase','prepare')
        state.update(phase=phase,action=action,summary=action if re.search(r'[\u4e00-\u9fff]',action) else state.get('summary') or dict(STEPS).get(phase,'正在处理任务'))
    elif kind=='subprocess':
        ident=str(payload.get('sessionId',''))[:100]
        if not ident:return
        children=state.setdefault('children',{})
        if ident not in children and len(children)>=32:children.pop(next(iter(children)))
        child=children.setdefault(ident,{'label':'计算子任务','status':'running'})
        if payload.get('label'):child['label']=str(payload['label'])[:100]
        if payload.get('action'):child['action']=str(payload['action'])[:180]
        status=payload.get('status')
        if status in {'running','completed','failed','stopped','interrupted'}:child['status']=status
    elif kind=='tool-end':state.pop('action',None)
    meta['processProgress']=process_progress(meta)


def process_progress(meta):
    state=meta.get('processState',{});status=meta.get('status','queued');cases=state.get('cases',[])
    if state.get('awaitingStart') and state.get('awaitingStartRound')==meta.get('promptRevision',0) and status!='running':status='queued'
    phase=state.get('phase','prepare');summary=state.get('summary') or ('等待执行' if status=='queued' else '正在准备任务')
    running=[c for c in state.get('children',{}).values() if c.get('status')=='running']
    if running:
        child=running[-1];summary=child.get('action') or '正在执行：'+child['label']
        if len(running)>1:summary+=f' · {len(running)} 个子任务进行中'
    elif state.get('reporting',{}).get('solved')==state.get('reporting',{}).get('total') and state.get('reporting',{}).get('total') and status not in TERMINAL:
        reporting=state['reporting'];phase='results';summary=f"求解 {reporting['solved']}/{reporting['total']} 已完成 · 结果提取 {reporting['collected']}/{reporting['total']}"
        if reporting.get('failed'):summary+=f" · {reporting['failed']} 组提取失败"
    elif cases and status not in TERMINAL:
        solving=[c for c in cases if c.get('execution',{}).get('status')=='running']
        if solving:
            phase='solve';current=solving[-1].get('solverTime');summary='正在求解'+(f' · t = {current:g}' if current is not None else '')
        elif any(c.get('latestTime') for c in cases):phase='results';summary='已有保存物理场，正在处理结果'
        elif any(c.get('meshReady') for c in cases):phase='mesh';summary='网格已生成，正在准备求解'
    if status in TERMINAL:
        phase='results' if status=='completed' else phase
        summary={'completed':'计算任务已结束','failed':'计算任务失败','stopped':'计算任务已停止','interrupted':'计算任务已中断'}[status]
        if status=='completed' and any(c.get('execution',{}).get('status')=='failed' for c in cases):summary='任务处理已结束，存在失败算例'
    index=next((i for i,(key,_) in enumerate(STEPS) if key==phase),0)
    stages=[{'id':key,'label':label,'status':'done' if status=='completed' or i<index else 'error' if status in {'failed','stopped','interrupted'} and i==index else 'active' if i==index and status not in TERMINAL else 'pending'} for i,(key,label) in enumerate(STEPS)]
    return {'summary':summary[:180],'stages':stages,'source':'process-observer','subprocesses':copy.deepcopy(list(state.get('children',{}).values()))}


class ProcessMonitor:
    def __init__(self,registry):
        self.registry=registry;self.stop=threading.Event();self.signatures={};self.errors={};self.reporting_cache={}
        self.thread=threading.Thread(target=self._run,name='workflow-progress-observer',daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.wait(1.5):
            with self.registry.lock:jobs=[(j['meta']['id'],j['workspace']) for j in self.registry.jobs.values() if not j['meta'].get('draft') and j['meta'].get('status') not in TERMINAL]
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
            if meta.get('processProgress')==next_:return
            meta['processProgress']=next_;r._save(job);r._emit(job,'state',r.public(job))
    def snapshot(self):return {'owner':'process-observer','running':self.thread.is_alive() and not self.stop.is_set(),'errors':dict(self.errors)}
    def close(self):self.stop.set();self.thread.join(timeout=2)
