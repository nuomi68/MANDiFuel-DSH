"""Independent, bounded evidence workers. All caches live outside solver workspaces."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from artifact_queue import ArtifactQueue
from workspace_watch import discover_cases

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from mandifuel_verify.case import Sources,stamp
from mandifuel_verify import engine_revision


def claim_status(claim, checks, state='ready'):
    if state!='ready':return 'stale'
    statuses=[check['status'] for check in checks if check['id'] in claim['checks']]
    for status in ['stale','failed','not_verified']:
        if status in statuses:return status
    return 'verified' if 'verified' in statuses else 'computed'


class EvidenceService:
    def __init__(self,registry):
        self.registry=registry;self.stop=threading.Event();self.lock=threading.RLock();self.reports={};self.states={};self.signatures={};self.pending={};self.requested=set();self.case_counts={};self.last_scan={};self.engine=engine_revision()
        for ident,job in registry.jobs.items():
            path=job['workspace'].parent/'evidence.json'
            try:
                data=json.loads(path.read_text())
                if data.get('engineRevision')==self.engine:self.reports[ident]=data['cases'];self.states[ident]='ready';self.signatures[ident]=data.get('signature');self.case_counts[ident]=data.get('caseCount',len(data['cases']))
            except (OSError,ValueError,KeyError):pass
        self.queue=ArtifactQueue(self.safe_build,workers=1)
        self.thread=threading.Thread(target=self.poll,name='independent-evidence-observer',daemon=True);self.thread.start()

    def _cache(self,ident):return self.registry._job(ident)['workspace'].parent/'evidence.json'

    def poll(self):
        while not self.stop.wait(2):
            current_engine=engine_revision()
            if current_engine!=self.engine:
                with self.lock:self.engine=current_engine;self.signatures.clear()
            with self.registry.lock:
                jobs=[(ident,j['meta'].get('status')) for ident,j in self.registry.jobs.items() if not j['meta'].get('draft')]
            with self.lock:
                self.requested.update(ident for ident,state in jobs if state in {'starting','running','importing'})
                jobs=[(ident,state) for ident,state in jobs if ident in self.requested]
            for ident,status in jobs:
                if self.stop.is_set():return
                # Active calculations are observed promptly. Historical results
                # need no full directory walk every two seconds; API reads still
                # validate every consumed source before returning a claim.
                now=time.monotonic();interval=2 if status in {'starting','running','importing'} or self.states.get(ident)=='pending' else 10
                if now-self.last_scan.get(ident,0)<interval:continue
                self.last_scan[ident]=now
                try:self.scan(ident)
                except (OSError,ValueError,KeyError):self.set_state(ident,'error')

    def case_signature(self,work,rows):
        values=[]
        for row in rows:
            case=work/row['caseRoot'];entries=[]
            for folder in ['0','system','constant']:
                for p in (case/folder).rglob('*'):
                    if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(work):entries.append((str(p.relative_to(work)),stamp(p)))
            for name in ['.mandifuel-execution.json','log.offbeat','log.mandifuel-runner']:
                p=case/name
                if p.is_file() and not p.is_symlink():entries.append((str(p.relative_to(work)),stamp(p)))
            for name in ['Cs','sourceCs','diffCs','T','Q','k','gradT','heatFluxVec','D','sigma']:
                p=case/(row.get('latestTime') or '0')/name
                if p.is_file() and not p.is_symlink():entries.append((str(p.relative_to(work)),stamp(p)))
            # Watch mesh instances, rather than resolving/reconstructing a mesh
            # on every poll. The verifier resolves each primitive once per run.
            # One directory probe per saved time also handles older point-only
            # overrides without seven missing-file probes per time directory.
            if row.get('latestTime'):
                selected=float(row['latestTime'])
                with os.scandir(case) as directories:
                    for directory in directories:
                        if not directory.is_dir(follow_symlinks=False):continue
                        try:value=float(directory.name)
                        except ValueError:continue
                        if not math.isfinite(value) or value>selected:continue
                        mesh=Path(directory.path)/'polyMesh'
                        if mesh.is_symlink() or not mesh.is_dir():continue
                        with os.scandir(mesh) as primitives:
                            for primitive in primitives:
                                if primitive.is_file(follow_symlinks=False):
                                    p=Path(primitive.path);entries.append((str(p.relative_to(work)),stamp(p)))
            entries.sort()
            values.append([row['caseRoot'],row.get('latestTime'),entries])
        return hashlib.sha256(json.dumps([self.engine,values],sort_keys=True).encode()).hexdigest()[:20]

    def scan(self,ident,force=False):
        with self.registry.lock:work=self.registry._job(ident)['workspace']
        rows=[r for r in discover_cases(work) if r.get('latestTime') and float(r['latestTime'])>0]
        with self.lock:self.case_counts[ident]=len(rows)
        rows=rows[:20]
        if not rows and not self.reports.get(ident):
            with self.lock:self.states[ident]='idle'
            return
        signature=self.case_signature(work,rows)
        with self.lock:
            if not force and self.signatures.get(ident)==signature:return
            before=self.pending.get(ident);self.pending[ident]=(signature,rows)
            settling=not force and (before is None or before[0]!=signature)
            if not settling:self.signatures[ident]=signature
        if settling:self.set_state(ident,'pending');return
        self.set_state(ident,'pending');self.queue.submit(ident)

    def safe_build(self,ident):
        try:self.build(ident)
        except Exception:
            self.set_state(ident,'error')
            raise

    def set_state(self,ident,state):
        with self.lock:
            if self.states.get(ident)==state:return
            self.states[ident]=state
        self.publish(ident)

    def publish(self,ident):
        r=self.registry
        with self.lock:
            cases=copy.deepcopy(self.reports.get(ident,[]));state=self.states.get(ident,'idle')
        revision=hashlib.sha256(json.dumps([state,[c.get('revision',c.get('error')) for c in cases]],sort_keys=True).encode()).hexdigest()[:20]
        with r.lock:
            if ident not in r.jobs:return
            job=r._job(ident);value={'revision':revision,'state':state,'cases':len(cases),'claims':sum(len(c.get('claims',[])) for c in cases)}
            if job['meta'].get('evidence')==value:return
            job['meta']['evidence']=value;r._save(job);r._emit(job,'state',r.public(job))

    def build(self,ident):
        with self.lock:signature,rows=copy.deepcopy(self.pending.get(ident,('',[])))
        with self.registry.lock:work=self.registry._job(ident)['workspace']
        cases=[]
        for row in rows:
            if self.stop.is_set():return
            try:
                run=subprocess.run([sys.executable,str(ROOT/'scripts/verify-results.py'),'--case',str(work/row['caseRoot']),'--workspace',str(work)],capture_output=True,text=True,timeout=45)
                if run.returncode not in {0,2}:raise ValueError((run.stderr or '核查程序失败')[-1000:])
                report=json.loads(run.stdout);cases.append(report)
            except (OSError,ValueError,subprocess.TimeoutExpired) as error:
                cases.append({'caseRoot':row['caseRoot'],'time':row.get('latestTime'),'state':'not_verified','error':str(error)[-1000:],'claims':[],'checks':[],'sources':[]})
        if self.stop.is_set():return
        current=self.case_signature(work,[r for r in discover_cases(work) if r.get('latestTime') and float(r['latestTime'])>0][:20])
        with self.lock:
            self.reports[ident]=cases;self.states[ident]='ready' if current==signature and all(c.get('state')!='stale' for c in cases) else 'pending'
            state=self.states[ident]
        from registry import atomic
        atomic(self._cache(ident),{'engineRevision':self.engine,'signature':signature,'cases':cases,'caseCount':self.case_counts.get(ident,len(cases))})
        self.publish(ident)
        if state=='pending':self.scan(ident,force=True)

    def fresh(self,work,case):
        if case.get('state')!='ready':return False
        reader=Sources(work)
        for source in case.get('sources',[]):
            try:
                if stamp(reader.path(source['path']))!=source['stamp']:return False
            except (OSError,ValueError):return False
        return True

    def index(self,ident,claim=None,source=None):
        with self.registry.lock:work=self.registry._job(ident)['workspace']
        with self.lock:
            self.requested.add(ident);cases=self.reports.get(ident,[])
            if claim:cases=[c for c in cases if any(item['id']==claim for item in c.get('claims',[]))]
            cases=copy.deepcopy(cases);state=self.states.get(ident,'idle')
        summaries=[];case_rows=[]
        for case in cases:
            fresh=self.fresh(work,case) and state not in {'pending','error'};case_state=case['state'] if fresh else 'stale' if case.get('claims') else case['state']
            checks=[{**c,'status':c['status'] if fresh else 'stale'} for c in case.get('checks',[])]
            case_rows.append({k:case.get(k) for k in ['caseRoot','time','error','revision']}|{'state':case_state,'checks':[{k:c.get(k) for k in ['id','key','title','status','reason']} for c in checks]})
            for item in case.get('claims',[]):
                status=claim_status(item,checks,case_state)
                execution=[c for c in checks if c['key']=='execution']
                summary={k:item[k] for k in ['id','key','title','caseRoot','time','timeUnit','value','unit']}
                summary.update(status=status,execution=execution[0]['status'] if execution else 'not_verified');summaries.append(summary)
                if item['id']!=claim:continue
                sources=[s for s in case['sources'] if s['id'] in item['sources']]
                if source:
                    selected=next((s for s in sources if s['id']==source),None)
                    if selected is None:raise ValueError('此结论未引用该原始文件')
                    reader=Sources(work);data=reader.read(selected['path']);sha=hashlib.sha256(data).hexdigest()
                    return {'path':selected['path'],'sha256':selected['sha256'],'currentSha256':sha,'changed':sha!=selected['sha256'],
                            'text':data[:128*1024].decode('utf-8',errors='replace'),'truncated':len(data)>128*1024}
                return {'claim':{**item,'status':status},'checks':checks,'sources':sources,'state':case_state,
                        'limits':case.get('limits',[]),'generatedAt':case.get('generatedAt'),'engine':case.get('engine'),'engineRevision':case.get('engineRevision')}
        if claim:raise ValueError('当前任务没有这个核查结论')
        if any(c['state']=='stale' for c in case_rows):state='pending'
        revision=hashlib.sha256(json.dumps([state,summaries,case_rows],sort_keys=True,allow_nan=False).encode()).hexdigest()[:20]
        return {'schema':'mandifuel.evidence-index/v1','revision':revision,'state':state,'claims':summaries,'cases':case_rows,
                'limits':{'automaticCaseLimit':20,'casesDetected':self.case_counts.get(ident,len(cases)),'uncheckedCases':max(0,self.case_counts.get(ident,len(cases))-20)},
                'policy':'独立程序核查；各项范围和容差分别列出；未核验不等于通过'}

    def close(self):
        self.stop.set();self.thread.join(timeout=3);self.queue.close()
