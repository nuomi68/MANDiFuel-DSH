"""Score frozen paired tasks and provider telemetry. No inference or solver calls."""
import argparse,csv,json,math,re,statistics
from collections import Counter
from pathlib import Path
from tasks import TASKS
from reference import times,values
ARMS=('bare','skill','skill_rag')
def read(p):return json.loads(p.read_text())
def lines(p):return [json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.is_file() else []
def oknum(v):return type(v) in (int,float) and math.isfinite(v)
def close(a,b):return oknum(a) and abs(a-b)<=max(abs(b)*.005,1e-12)
def trace_info(folder):
    sessions=list((folder/'traces').rglob('session.jsonl'))
    usage=Counter();calls=Counter();configs=[];reasons=[];ragids=set();returned=set();ui_or_subagent=False;rag_confirmed=set()
    messages=covered=0
    for p in sessions:
        for line in p.open():
            row=json.loads(line);d=row.get('data',{});typ=row['type']
            if typ=='request/header':
                cfg=d.get('header',d).get('config',{});c=[cfg.get(k) for k in ('provider','model','reasoningEffort')]
                if c not in configs:configs.append(c)
            elif typ=='tool/call':
                name=d['name'];calls[name]+=1;arg=d['arguments'];arg=json.loads(arg) if isinstance(arg,str) else arg
                command=arg.get('command','') if isinstance(arg,dict) else ''
                if name in ('bash','terminal') and re.search(r'(experience_rag\.py[\x22\x27]?\s+query\b|dual_query\.py[\x22\x27]?\s+--)',command):
                    ragids.add(d['callId'])
                if name.startswith('ui_') or name in ('task','spawn_agent'):ui_or_subagent=True
            elif typ=='tool/result':
                msg=d['message'];cid=msg.get('source',{}).get('callId')
                if cid in ragids:
                    for part in msg.get('content',[]):
                        if part.get('isError'):continue
                        for v in part.get('content',[]):
                            txt=v.get('text','')
                            if '"mandifuel-experience-rag.v1"' in txt or re.search(r'knowledge:K\d',txt):
                                if 'knowledge:' in txt or '"status":"ok"' in txt.replace(' ',''):
                                    rag_confirmed.add(cid)
                                    returned.update(re.findall(r'knowledge:K[\w-]+:\d+',txt))
            elif typ=='assistant/message':
                messages+=1
                if d.get('usage'):
                    covered+=1;usage.update(d['usage'])
            elif typ=='turn/end':reasons.append(d.get('reason',{}).get('kind'))
    return {'total_tokens':usage['totalTokens'],'uncached_input':usage['inputTokens'],'cached_input':usage['cacheReadTokens'],
            'model_output':usage['outputTokens'],'reasoning_subset':usage['reasoningTokens'],'uncached_plus_output':usage['inputTokens']+usage['outputTokens'],
            'model_messages':messages,'messages_with_usage':covered,'tool_calls':sum(calls.values()),'skill_calls':calls['skill'],
            'rag_invocations':len(ragids),'rag_observed_returns':len(rag_confirmed),'returned_ids':sorted(returned),'session_count':len(sessions),
            'configs':configs,'turn_ends':reasons,'ui_or_subagent_tools':ui_or_subagent}
def native_exit_evidence(folder,work):
    """Recover direct solver invocations which selected the real binary in PATH."""
    calls={};matched={}
    for p in (folder/'traces').rglob('session.jsonl'):
        for line in p.open():
            row=json.loads(line);d=row.get('data',{})
            if row['type']=='tool/call' and d['name']=='bash':
                a=d['arguments'];a=json.loads(a) if isinstance(a,str) else a
                cmd=a.get('command','')
                if re.search(r'(?:^|[;&|/\s])offbeat\s*(?:>|-|[;&|]|$)',cmd) or 'bash Allrun' in cmd:
                    calls[d['callId']]=cmd
            elif row['type']=='tool/result':
                m=d['message'];cmd=calls.get(m.get('source',{}).get('callId'),'')
                if not cmd:continue
                for item in m['content']:
                    s='\n'.join(i.get('text','') for i in item.get('content',[]))
                    if item.get('isError') or not re.search(r'(?im)^(?:offbeat\s+)?(?:exit(?:\s+code)?|rc)\s*[=:]\s*0\b',s):continue
                    for log in work.rglob('log.offbeat*'):
                        if not log.is_file() or 'execution-evidence' in log.parts:continue
                        case=log.parent
                        if str(case) not in cmd:continue
                        data=log.read_text(errors='replace')
                        if (re.search(r'(?m)^Exec\s*:\s*(?:\S*/)?offbeat\b',data)
                            and re.search(r'(?m)^Case\s*:\s*'+re.escape(str(case))+r'\s*$',data)
                            and re.search(r'(?im)^\s*end\s*$',data)):
                            matched[case]=log
    return matched
def execution(t,root,folder,answer):
    work=folder/'workspace';exits=lines(work/'solver-exits.jsonl')
    starts=[x for x in lines(work/'solver-starts.jsonl') if x.get('kind')=='solve']
    if t[3]!='solve':
        return {'solver_wrapper_starts':len(starts),'execution_ok':not starts and not native_exit_evidence(folder,work),'result_root':'','raw_values':None}
    expected_time=float(times(root/'calibration'/t[0])[-1])
    last=None
    completed_case=None
    for x in exits:
        if x.get('kind')!='solve' or x.get('exit_code')!=0:continue
        c=Path(x['case_root']).resolve()
        if not c.is_dir() or not c.is_relative_to(work.resolve()) or c.is_relative_to((work/'source-case').resolve()):continue
        tm=times(c)
        if not tm or float(tm[-1])<=0:continue
        log=work/'execution-evidence'/x['id']/'solver.log'
        if not log.exists():log=c/'log.offbeat'
        if not log.exists() or not re.search(r'^\s*end\s*$',log.read_text(errors='replace'),re.I|re.M):continue
        completed_case=c
        if math.isclose(float(tm[-1]),expected_time,rel_tol=1e-9,abs_tol=1e-8):
            last=c
    source='wrapper' if completed_case else ''
    if last is None:
        for c in native_exit_evidence(folder,work):
            tm=times(c)
            if not c.is_relative_to(work/'source-case') and tm and float(tm[-1])>0:
                completed_case=c
                source='native_log_and_traced_exit'
                if math.isclose(float(tm[-1]),expected_time,rel_tol=1e-9,abs_tol=1e-8):
                    last=c;source='native_log_and_traced_exit'
    result={'solver_wrapper_starts':len(starts),'exit_evidence':source,'execution_ok':last is not None,'result_root':str(last.relative_to(work)) if last else '', 'raw_values':None}
    audited=last or completed_case
    result['expected_final_time']=expected_time
    result['actual_final_time']=float(times(audited)[-1]) if audited else None
    result['terminal_complete']=audited is not None
    if audited:
        result['result_root']=str(audited.relative_to(work))
        try:result['raw_values']=list(values(t,audited))
        except Exception as exc:result['raw_error']=str(exc)
    return result
def score(t,arm,root):
    tid=t[0];f=root/tid/arm;w=f/'workspace';record=read(f/'run.json');ref=read(root/'reference.json')[tid];tr=trace_info(f)
    try:ans=read(w/'answer.json')
    except (OSError,ValueError):ans={}
    if not isinstance(ans,dict):ans={}
    a,b=[ans.get(k) for k in ('a','b')]
    ev=execution(t,root,f,ans)
    structural=all([record.get('exit_code')==0,not record.get('timed_out'),tr['turn_ends']==['completed'],record['source_unchanged'],ev['execution_ok'],oknum(a),oknum(b),isinstance(ans.get('source'),str) and bool(ans['source'].strip())])
    checks=[close(x,y) for x,y in zip([a,b],ref)]
    raw_checks=[close(x,y) for x,y in zip(ev['raw_values'],ref)] if ev['raw_values'] else None
    # Frozen main endpoints: both submitted quantities against the blind reference.
    # Fresh raw-field recomputation is reported as a separate independent audit.
    return {'id':tid,'title':t[1],'mode':t[3],'arm':arm,'task_pass':bool(structural),'physics_pass':bool(structural and all(checks)),
            'a':a,'a_ref':ref[0],'a_unit':t[5][0],'a_match':checks[0],'b':b,'b_ref':ref[1],'b_unit':t[5][1],'b_match':checks[1],
            'raw_checks':raw_checks,'exit_code':record.get('exit_code'),'wall_s':record['wall_seconds'],'input_preserved':record['source_unchanged'],
            'source_stated':bool(ans.get('source')),'preflight':read(f/'preflight.json')['isolation']['passed'],**ev,**tr}
def brief(rows):
    return {'n':len(rows),'task_pass':sum(x['task_pass'] for x in rows),'physics_pass':sum(x['physics_pass'] for x in rows),
            'endpoint_matches':sum(x['a_match']+x['b_match'] for x in rows),'tokens':sum(x['total_tokens'] for x in rows),
            'median_tokens':statistics.median(x['total_tokens'] for x in rows),'uncached_input':sum(x['uncached_input'] for x in rows),
            'cached_input':sum(x['cached_input'] for x in rows),'model_output':sum(x['model_output'] for x in rows),
            'uncached_plus_output':sum(x['uncached_plus_output'] for x in rows),'rag_sessions':sum(x['rag_invocations']>0 for x in rows),
            'confirmed_rag_sessions':sum(x['rag_observed_returns']>0 for x in rows)}
def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
    progress=read(root/'progress.json')
    assigned={(t[0], arm) for t in TASKS for arm in ARMS}
    finished={(record['task_id'],record['arm']) for record in progress}
    if finished != assigned or len(progress) != len(assigned):
        raise SystemExit(f'Incomplete cohort: {len(finished)} of {len(assigned)} distinct task/arm records')
    errors=[(r['task_id'],r['arm'],r['infrastructure_error']) for r in progress if r.get('infrastructure_error')]
    if errors:
        raise SystemExit(f'Infrastructure errors; aggregate withheld pending audit: {errors}')
    cal=read(root/'calibration.json');refs=read(root/'reference.json')
    assert all(cal[t[0]]['exit_code']==0 and all(close(x,y) for x,y in zip(cal[t[0]]['values'],refs[t[0]])) for t in TASKS[:8])
    rows=[score(t,a,root) for t in TASKS for a in ARMS]
    for r in rows:
        assert r['session_count']==1 and r['preflight'] and not r['ui_or_subagent_tools'] and r['configs']==[['deepseek-official','deepseek-v4-flash','high']],r
        assert r['model_messages']==r['messages_with_usage'] and r['total_tokens']==r['uncached_input']+r['cached_input']+r['model_output'],r
        assert not(r['arm']=='bare' and r['skill_calls']) and not(r['arm']!='skill_rag' and r['rag_invocations']),r
    groups={a:brief([r for r in rows if r['arm']==a]) for a in ARMS}
    splits={m:{a:brief([r for r in rows if r['arm']==a and r['id'].startswith(m)]) for a in ARMS} for m in 'SPD'}
    (root/'scores.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    (root/'aggregate.json').write_text(json.dumps({'arms':groups,'strata':splits},ensure_ascii=False,indent=2))
    cols=['id','title','arm','task_pass','physics_pass','a','a_ref','a_unit','a_match','b','b_ref','b_unit','b_match','total_tokens','uncached_input','cached_input','model_output','uncached_plus_output','model_messages','tool_calls','skill_calls','rag_invocations','rag_observed_returns','solver_wrapper_starts','exit_evidence','expected_final_time','actual_final_time','terminal_complete','raw_checks','wall_s','execution_ok','input_preserved','result_root']
    with (root/'paired.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.DictWriter(f,cols,extrasaction='ignore');out.writeheader();out.writerows(rows)
    print(json.dumps(groups,ensure_ascii=False))
if __name__=='__main__':main()
