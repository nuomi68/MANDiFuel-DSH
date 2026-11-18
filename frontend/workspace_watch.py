"""Local, bounded file observation and owned presentation artifacts; never solves.

The solver owns its plans and handoff. This observer writes a separate index so
file discovery cannot race with or overwrite those files. Study ownership is
accepted only from explicit caseRoot bindings.
"""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import re
import time
import threading

INDEX='delivery/workspace-observation.json'
SCHEMA='mandifuel.workspace-observation/v1'
IGNORE={'delivery','.git','sources','source-case','reference-case','source-candidates','node_modules','__pycache__'}


def completed_frame(case):
    receipt=case['execution']
    if not (case['meshReady'] and case['fields'] and case['latestTime'] and receipt.get('status')=='completed'
            and receipt.get('terminal_marker') is True and receipt.get('exit_code')==0):return False
    try:return Decimal(case['latestTime'])==Decimal(str(receipt.get('final_time')))
    except (InvalidOperation,ValueError):return False


def local_file(work,path):
    path=Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(work.resolve()):return False
    return path.is_file()


def stamp(path):
    s=path.stat();return [s.st_mtime_ns,s.st_size]


def discover_cases(work,roots=()):
    work=Path(work).resolve();found={}
    for base,dirs,files in os.walk(work,followlinks=False):
        rel=Path(base).relative_to(work)
        dirs[:]=sorted(d for d in dirs if d not in IGNORE and not (Path(base)/d).is_symlink())
        if len(rel.parts)>5:dirs[:]=[];continue
        if 'system' in dirs and 'constant' in dirs and local_file(work,Path(base)/'system/controlDict'):
            found[str(rel) or '.']=Path(base)
            dirs[:]=[d for d in dirs if d not in {'system','constant','0'} and not re.fullmatch(r'[0-9.eE+-]+',d)]
    for root in roots:
        case=(work/root).resolve()
        if case.is_relative_to(work) and local_file(work,case/'system/controlDict'):found[str(case.relative_to(work)) or '.']=case
    cases=[]
    for root,case in sorted(found.items()):
        mesh=case/'constant/polyMesh';ready=all(local_file(work,mesh/n) for n in ('points','faces','owner','neighbour','boundary'))
        times=[]
        for d in case.iterdir():
            if not d.is_dir() or d.is_symlink():continue
            try:value=float(d.name)
            except ValueError:continue
            if math.isfinite(value) and value>0:times.append((value,d))
        latest=max(times,key=lambda t:t[0])[1] if times else None
        fields=[];signature=[]
        if latest:
            for p in sorted(latest.iterdir()):
                if local_file(work,p) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',p.name):fields.append(p.name);signature.append([p.name,*stamp(p)])
        receipt={};receipt_path=case/'.mandifuel-execution.json'
        if local_file(work,receipt_path):
            try:
                raw=json.loads(receipt_path.read_text());receipt={k:raw[k] for k in ('status','exit_code','final_time','terminal_marker') if k in raw}
            except (ValueError,OSError):pass
        inputs=[]
        for name in ('0','constant','system'):
            for base,dirs,files in os.walk(case/name,followlinks=False):
                dirs[:]=sorted(d for d in dirs if d!='polyMesh' and not (Path(base)/d).is_symlink())
                for filename in sorted(files):
                    p=Path(base)/filename
                    if not filename.startswith('.') and local_file(work,p):inputs.append([str(p.relative_to(work)),*stamp(p)])
        cases.append({'caseRoot':root,'meshReady':ready,'latestTime':latest.name if latest else None,'fields':fields,'signature':signature,'meshSignature':[stamp(mesh/n) for n in ('points','faces','owner','neighbour','boundary')] if ready else [],'inputs':inputs,'execution':receipt})
    return cases


def structured_files(work,cache):
    """Recognize data shapes, rather than case-specific inversion filenames."""
    files=[]
    candidates=[]
    for base,dirs,names in os.walk(work,followlinks=False):
        rel=Path(base).relative_to(work)
        dirs[:]=[d for d in dirs if d not in IGNORE and d not in {'case','cases','attempts','constant','system','0','scripts'} and not (Path(base)/d).is_symlink()] if len(rel.parts)<3 else []
        # Host-generated models and observation overlays are already consumed
        # by _import. They are not new engineering evidence for a UI worker.
        if rel==Path('delivery'):dirs[:]=[d for d in dirs if d not in {'views','observed'}]
        for name in names:
            p=Path(base)/name
            if p.suffix.lower()=='.json':candidates.append(p)
            elif p.suffix.lower() in {'.csv','.md','.txt','.png','.jpg','.jpeg','.webp'} and p.name not in {'AGENTS.md','resources.md','request.txt'} and local_file(work,p) and p.stat().st_size<=10*1024*1024:
                files.append({'path':str(p.relative_to(work)),'kind':'artifact','stamp':stamp(p)})
    candidates.extend((work/'delivery').glob('*.json'))
    for p in sorted(candidates):
        if p.name in {'workbench.json','workspace-observation.json'} or not local_file(work,p) or p.stat().st_size>4*1024*1024:continue
        key=str(p.relative_to(work));signature=stamp(p)
        if cache.get(key,{}).get('stamp')==signature:kind=cache[key]['kind']
        else:
            try:
                value=json.loads(p.read_text());kind=None
                if isinstance(value,dict):
                    if value.get('schema') in {'mandifuel.viewer/v1','mandifuel.mesh/v1'}:pass
                    elif value.get('schema')=='mandifuel.study/v1':kind='study'
                    elif isinstance(value.get('study'),dict) and value['study'].get('schema')=='mandifuel.study/v1':kind='study-definition'
                    elif isinstance(value.get('columns'),list) and isinstance(value.get('rows'),list):kind='table'
                    elif isinstance(value.get('evaluations'),list):kind='evaluations'
                    elif isinstance(value.get('rows'),list):kind='records'
                    else:kind='report'
                elif isinstance(value,list) and value and all(isinstance(r,dict) and 'point' in r and 'status' in r for r in value):kind='history'
                elif isinstance(value,list) and value and all(isinstance(r,dict) for r in value):kind='records'
                cache[key]={'stamp':signature,'kind':kind}
            except (ValueError,OSError):continue # Incomplete JSON must not become a wakeup.
        if kind:files.append({'path':key,'kind':kind,'stamp':signature})
    for key in list(cache):
        if not (work/key).is_file():cache.pop(key,None)
    return files


class WorkspaceWatcher:
    def __init__(self,settle_seconds=1.,clock=time.monotonic):
        self.settle_seconds=settle_seconds;self.clock=clock;self.pending={};self.accepted={};self.file_cache={};self.attempts={};self.commit_lock=threading.RLock()

    def scan(self,ident,work,study=None):
        work=Path(work).resolve();roots=[r['caseRoot'] for r in (study or {}).get('runs',[]) if r.get('caseRoot')]
        cases=discover_cases(work,roots);files=structured_files(work,self.file_cache.setdefault(ident,{}))
        mapping=work/'delivery/observed/study-map.json'
        state={'cases':cases,'files':files,'mapping':stamp(mapping) if local_file(work,mapping) else None};signature=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest();now=self.clock()
        if self.accepted.get(ident)==signature:return None
        previous=self.pending.get(ident)
        if not previous or previous[0]!=signature:self.pending[ident]=(signature,now);return None
        if now-previous[1]<self.settle_seconds:return None
        self.accepted[ident]=signature
        return {**state,'signature':signature}

    def reconcile(self,work,observation,study,views,title,render_models=True):
        """Create only models whose run owner and result status are explicit."""
        from registry import atomic,inside,read_json,validate_bundle
        from export_case import export_case,export_mesh
        work=Path(work).resolve();path=work/INDEX
        path.parent.mkdir(parents=True,exist_ok=True)
        try:index=read_json(path)
        except (ValueError,OSError):index={}
        prior=index if index.get('schema')==SCHEMA else {}
        mapped=False
        mapping_path=work/'delivery/observed/study-map.json'
        if local_file(work,mapping_path):
            try:
                mapping=read_json(mapping_path);study=mapped_history_study(work,mapping);mapped=True
                output=work/'delivery/observed/study.json'
                with self.commit_lock:
                    if not output.exists() or read_json(output)!=study:atomic(output,study)
            except (ValueError,OSError,KeyError):
                output=work/'delivery/observed/study.json'
                if prior.get('study')=='delivery/observed/study.json' and output.is_file():study=read_json(output);mapped=True
        study=copy.deepcopy(study or {});case_bindings=copy.deepcopy(prior.get('caseBindings',[]))
        for spec in observation['files']:
            if spec['kind']!='history':continue
            try:records=read_json(work/spec['path'])
            except (ValueError,OSError):continue
            for record in records:
                run=next((r for r in study.get('runs',[]) if r['id']==record.get('point',{}).get('id')),None)
                if not run or run.get('caseRoot') or not isinstance(record.get('result_root'),str):continue
                try:root=inside(work,record['result_root'])
                except ValueError:continue
                if not local_file(work,root/'system/controlDict'):continue
                run['caseRoot']=str(root.relative_to(work));case_bindings.append({'runId':run['id'],'caseRoot':run['caseRoot'],'source':spec['path']})
        bindings=[];cases={c['caseRoot']:c for c in observation['cases']};errors=[]
        old={row['runId']:row for row in prior.get('models',[])}
        for run in (study or {}).get('runs',[]):
            if not run.get('caseRoot') or run['status'] in {'failed','skipped'}:continue
            root=str(inside(work,run['caseRoot']).relative_to(work));case=cases.get(root)
            if not case or not case['meshReady']:continue
            if not render_models:
                previous=old.get(run['id'])
                if previous and previous.get('caseRoot')==root:bindings.append(previous)
                continue
            explicit=[v for v in views if v['id'] in run.get('viewIds',[]) and not v['id'].startswith('observed-')]
            # An explicit delivered result wins. An initial mesh can be upgraded.
            if any(v['kind']=='results' for v in explicit):continue
            selectors=run.get('preview',{}).get('fields') or (study or {}).get('preview',{}).get('fields')
            kind='results' if run['status'] in {'running','completed'} and (selectors or completed_frame(case)) and case['latestTime'] and case['execution'].get('status') not in {'failed','interrupted'} else 'mesh'
            if kind=='mesh' and explicit:continue
            key='observed-'+hashlib.sha256((run['id']+'\0'+root).encode()).hexdigest()[:20]
            target=work/'delivery/observed'/f'{key}.json';target.parent.mkdir(parents=True,exist_ok=True)
            source_signature=hashlib.sha256(json.dumps([root,kind,case['meshSignature'],case['signature'] if kind=='results' else [],selectors],sort_keys=True).encode()).hexdigest()
            previous=old.get(run['id'],{});attempt=(str(work),run['id'],source_signature)
            if previous.get('sourceSignature')!=source_signature or not target.exists():
                if self.attempts.get(attempt,0)>time.monotonic():
                    if previous:bindings.append(previous)
                    continue
                temp=target.with_suffix('.next.json')
                try:
                    if kind=='results':export_case(work/root,temp,title=title,selectors=selectors,time=run.get('preview',{}).get('time',(study or {}).get('preview',{}).get('time','latest')),write_handoff=False)
                    else:export_mesh(work/root,temp,title=title,write_handoff=False)
                    validate_bundle(read_json(temp));temp.replace(target)
                except (ValueError,OSError,KeyError) as error:
                    self.attempts[attempt]=time.monotonic()+5;errors.append({'runId':run['id'],'message':str(error)[:300]})
                    if previous:bindings.append(previous)
                    # Retry a transient partial field without repeatedly waking an agent.
                    continue
            bindings.append({'runId':run['id'],'caseRoot':root,'id':key,'label':(run.get('label') or run['id'])+(' · 已保存场' if kind=='results' else ' · 网格预览'),'viewer':str(target.relative_to(work)),'sourceSignature':source_signature})
        # A loose collection of completed cases can have real fields without a
        # study plan. Expose the physical case roots without assigning run IDs.
        recovered=[]
        owned={v['id'] for v in prior.get('caseViews',[])}
        needs_recovery=len(cases)>1 or any(v['id'] not in {'mesh-preview','live-results'} for v in views)
        if not study and needs_recovery and not any(v['kind']=='results' and v['id'] not in owned for v in views):
            previous_views={v['caseRoot']:v for v in prior.get('caseViews',[])}
            for root,case in cases.items():
                if not completed_frame(case):continue
                key='saved-case-'+hashlib.sha256(root.encode()).hexdigest()[:20]
                relative=f'delivery/observed/{key}.json'
                signature=hashlib.sha256(json.dumps([case['latestTime'],case['meshSignature'],case['signature']]).encode()).hexdigest()
                ref={'id':key,'caseRoot':root,'label':root[-60:],'viewer':relative,'sourceSignature':signature}
                if previous_views.get(root)==ref and local_file(work,work/relative):
                    recovered.append(ref)
                elif render_models:
                    target=work/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    temp=target.with_suffix('.next.json')
                    try:
                        export_case(work/root,temp,title=title,time=case['latestTime'],write_handoff=False)
                        validate_bundle(read_json(temp));temp.replace(target);recovered.append(ref)
                    except (ValueError,OSError,KeyError) as error:
                        errors.append({'caseRoot':root,'message':str(error)[:300]})
                    finally:temp.unlink(missing_ok=True)
        inputs=sorted({entry[0] for case in observation['cases'] for entry in case['inputs']})
        files={row['path'] for row in observation['files']}
        for case in observation['cases']:
            for name in ('.mandifuel-execution.json','prepare.json','log.offbeat','log.mandifuel-runner'):
                p=work/case['caseRoot']/name
                if local_file(work,p) and (name!='log.offbeat' or case['execution'].get('status') in {'completed','failed','interrupted'}):files.add(str(p.relative_to(work)))
        next_index={'schema':SCHEMA,'revision':prior.get('revision',0)+1,'signature':observation['signature'],'inputs':inputs,'files':sorted(files),'models':bindings,'caseBindings':case_bindings,'events':[{'kind':'case','caseRoot':c['caseRoot'],'meshReady':c['meshReady'],'latestTime':c['latestTime'],'fields':c['fields'],'execution':c['execution']} for c in observation['cases']][-20:]+[{'kind':row['kind'],'path':row['path']} for row in observation['files']][-12:],'errors':errors}
        if recovered:next_index['caseViews']=recovered
        if mapped:next_index['study']='delivery/observed/study.json'
        elif any(row['path']=='delivery/study.json' and row['kind']=='study' for row in observation['files']):next_index['study']='delivery/study.json'
        with self.commit_lock:
            try:current=read_json(path)
            except (ValueError,OSError):current={}
            if render_models and current and current.get('signature') not in {prior.get('signature'),observation['signature']}:return current
            if not render_models:
                # A renderer may have completed since the inventory read its index.
                allowed={r['id']:r.get('caseRoot') for r in study.get('runs',[])}
                next_index['models']=[b for b in current.get('models',bindings) if allowed.get(b['runId'])==b['caseRoot']]
                if current.get('signature')==observation['signature'] and current.get('caseViews') and not study:
                    next_index['caseViews']=current['caseViews']
            same=lambda value:{k:v for k,v in value.items() if k!='revision'}
            if same(next_index)==same(current):return current
            next_index['revision']=current.get('revision',0)+1;atomic(path,next_index)
            return next_index


def mapped_history_study(work,mapping):
    """An explicit UI-side mapping of ordinary terminal Study records."""
    from registry import inside,read_json
    from export_study import history_study
    from study import validate_study
    if not isinstance(mapping,dict) or set(mapping)!={'history','study'} or not isinstance(mapping['study'],dict):raise ValueError('研究历史映射无效')
    path=inside(work,mapping['history'])
    if path.stat().st_size>16*1024*1024:raise ValueError('研究历史超出观察大小限制')
    history=read_json(path);value=history_study(history,mapping['study'])
    # Origins come from the ordinary executor's explicit record, never a name.
    for row,record in zip(value['runs'],history):
        if isinstance(record.get('result_root'),str):
            root=inside(work,record['result_root'])
            if local_file(work,root/'system/controlDict'):row['caseRoot']=str(root.relative_to(work))
    return validate_study(value)


def history_facts(work,files):
    from registry import inside,read_json
    result=[]
    for spec in files:
        if spec.get('kind')!='history':continue
        try:
            rows=read_json(inside(work,spec['path']));samples=[]
            for row in rows[:3]:
                sample={k:row[k] for k in ['point','status','response','reporting_response','result_root'] if k in row}
                if len(json.dumps(sample))<=6000:samples.append(sample)
            result.append({'file':spec['path'],'count':len(rows),'samples':samples})
        except (ValueError,OSError):continue
    return result[:4]
