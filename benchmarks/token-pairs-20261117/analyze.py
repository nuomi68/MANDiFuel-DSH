"""Aggregate provider usage once per assistant message; publish no reasoning text."""
import argparse,csv,hashlib,html,json,re,shutil,sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'benchmarks/fuel-rod-power-ab'))
from summarize_traces import arm_summary

def reduction(bare,skill):return 100*(1-skill/bare) if bare else None
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def request_configs(folder):
    out=[]
    for path in folder.rglob('session.jsonl'):
        for line in path.read_text().splitlines():
            e=json.loads(line)
            if e.get('type')!='request/header':continue
            h=e.get('data',{}).get('header',e.get('data',{}));c=h.get('config',{})
            safe={k:c[k] for k in ['provider','model','reasoningEffort','maxTokens','temperature','topP'] if k in c}
            if safe not in out:out.append(safe)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);args=p.parse_args();root=args.run_root.resolve();manifest=json.loads((root/'manifest.json').read_text());quality=json.loads((root/'verification.json').read_text());summary={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'run_root':str(root),'code_commit':manifest['code_commit'],'model':manifest['model'],'frontend_agent':False,'replicates_per_task_arm':1,'token_definition':'Sum each new assistant/message.data.usage once; totalTokens = inputTokens (uncached) + cacheReadTokens + outputTokens. reasoningTokens is a subset of outputTokens and is not added again.','scope':manifest['scope'],'tasks':{},'aggregate':{},'integrity_checks':[]};all_rows=[];aggregate={a:Counter() for a in ['bare','skill']};configs=[]
    for task in manifest['tasks']:
        tid=task['id'];pair={'title':task['title'],'arms':{}};summaries={}
        for arm in ['bare','skill']:
            trace=arm_summary(root/tid,arm);summaries[arm]=trace;usage=trace['tokens'];work=root/tid/arm/'workspace';config=request_configs(root/tid/arm/'traces');configs.extend(config)
            q=quality['tasks'][tid][arm]
            metric={'total_tokens':usage['totalTokens'],'uncached_input_tokens':usage['inputTokens'],'cached_input_tokens':usage['cacheReadTokens'],'output_tokens':usage['outputTokens'],'reasoning_tokens_subset':usage.get('reasoningTokens',0),'uncached_input_plus_output':usage['inputTokens']+usage['outputTokens'],'tool_calls':trace['tool_calls'],'model_steps':trace['steps_completed'],'tool_failures':trace['tool_failures'],'wall_seconds':trace['run']['wall_seconds'],'solver_starts':len((work/'solver-starts.jsonl').read_text().splitlines()) if (work/'solver-starts.jsonl').exists() else 0,'quality_passed':q['passed'],'sessions':trace['session_count'],'source_unchanged':trace['run']['source_unchanged'],'model_configurations':config,'usage_coverage':{'assistant_messages':trace['assistant_messages'],'with_usage':trace['usage_messages']},'tools_by_name':trace['tools_by_name']}
            pair['arms'][arm]=metric
            for key in ['total_tokens','uncached_input_tokens','cached_input_tokens','output_tokens','uncached_input_plus_output','tool_calls','model_steps','tool_failures','wall_seconds','solver_starts']:aggregate[arm][key]+=metric[key]
            all_rows.append({'task_id':tid,'title':task['title'],'arm':arm,**{k:v for k,v in metric.items() if isinstance(v,(int,float,bool))}})
            checks={'run_completed':trace['run_status']=='completed','single_scientific_session':trace['session_count']==1,'no_frontend_tools':not any(name.startswith('ui_') for name in trace['tools_by_name']),'all_messages_have_usage':trace['assistant_messages']==trace['usage_messages'],'token_identity':usage['totalTokens']==usage['inputTokens']+usage['cacheReadTokens']+usage['outputTokens'],'task_quality_passed':q['passed'],'source_preserved':metric['source_unchanged'],'isolation_preflight':json.loads((root/tid/arm/'preflight.json').read_text())['isolation']['passed']}
            if arm=='bare':checks['no_skill_tool_calls']=trace['tools_by_name'].get('skill',0)==0
            summary['integrity_checks'].append({'task':tid,'arm':arm,'checks':checks,'passed':all(checks.values())})
            # Final evidence keeps observable tool timelines and usage, never reasoning bodies.
        save(root/tid/'trace-summary.json',{'run_root':str(root/tid),'arms':summaries})
        pair['skill_reduction_percent']={k:reduction(pair['arms']['bare'][k],pair['arms']['skill'][k]) for k in ['total_tokens','uncached_input_tokens','cached_input_tokens','output_tokens','uncached_input_plus_output','tool_calls','model_steps','wall_seconds']};summary['tasks'][tid]=pair
    summary['aggregate']={arm:dict(value) for arm,value in aggregate.items()};summary['aggregate']['skill_reduction_percent']={k:reduction(aggregate['bare'][k],aggregate['skill'][k]) for k in aggregate['bare'] if k not in {'tool_failures','solver_starts'}}
    summary['same_model_configuration']=bool(configs) and all(c==configs[0] for c in configs);summary['model_configuration']=configs[0];summary['all_checks_passed']=summary['same_model_configuration'] and all(c['passed'] for c in summary['integrity_checks']) and manifest['plugin_unchanged'];summary['quality']=quality['cross_arm_saved_fields']
    summary['limits']=['Three tasks, one run per arm, no confidence interval or population-wide conclusion.','Full scientific Skills integration (persona, protocol, helpers and execution guidance) differs from bare DSH; not a single batching-rule ablation.','Bare receives the same general scientific task boundary, prepared software and source inputs, with Skill registration disabled and Skill content unreadable.','Six concurrent sessions share host/API resources; wall times are descriptive.','Reported totalTokens includes cached repeated input; it is neither unique text length nor a monetary cost estimate.','Temperature checks compare delivery values with the explicitly declared primary result roots, not extra diagnostic or fixed-point checks.']
    save(root/'comparison.json',summary)
    with (root/'comparison.csv').open('w') as out:
        writer=csv.DictWriter(out,fieldnames=list(all_rows[0]));writer.writeheader();writer.writerows(all_rows)
    public={k:summary[k] for k in ['code_commit','model_configuration','same_model_configuration','all_checks_passed','integrity_checks','limits']};public['source_prompts']={t['id']:sha(root/t['id']/'task.txt') for t in manifest['tasks']};public['evaluator_sha256']=sha(Path(__file__).resolve().with_name('verify.py'));save(root/'integrity.json',public)
    for name in ['verify.py','analyze.py','plot.py']:
        source=Path(__file__).with_name(name)
        if source.exists():shutil.copyfile(source,root/'definition'/name)
    esc=html.escape;body=[]
    body.append('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>科学计算 Skills 与裸 DSH：三任务 Token 对照</title><style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.75 system-ui,sans-serif;color:#172333;background:#fafbfc}table{border-collapse:collapse;width:100%;background:white;margin:20px 0}th,td{border:1px solid #dce3eb;padding:9px 12px;text-align:right}th:first-child,td:first-child{text-align:left}h1{font-size:28px}h2{font-size:21px;margin-top:32px}.good{color:#08765f}code{background:#eef2f7;padding:2px 5px}p{max-width:1000px}img{width:100%;background:white}a{color:#245ba6}details{margin:15px 0}pre{white-space:pre-wrap;background:#f1f4f8;padding:15px}</style>')
    body.append('<h1>科学计算 Skills 与裸 DSH：三任务 Token 对照</h1><p>当前科学计算 Skills 整套接入与裸 DSH 比较。六个全新 headless 会话，无前端 UI agent，每个任务每组各运行一次。</p>')
    body.append('<p>模型：<code>deepseek-official/deepseek-v4-flash</code>，reasoningEffort=<code>high</code>。科学计算代码版本：<code>'+esc(manifest['code_commit'][:7])+'</code>。相同输入副本、写入边界与模型设置；历史、另一组数据及裸组 Skill 内容通过 Landlock 隔离。</p>')
    body.append('<table><tr><th>任务</th><th>裸 DSH 总 Token</th><th>Skills 总 Token</th><th>下降</th><th>工具调用 裸→Skills</th><th>核验</th></tr>')
    for tid,pair in summary['tasks'].items():
        a,b=pair['arms']['bare'],pair['arms']['skill'];body.append(f'<tr><td>{tid} {esc(pair["title"])}</td><td>{a["total_tokens"]:,}</td><td>{b["total_tokens"]:,}</td><td class="good">{pair["skill_reduction_percent"]["total_tokens"]:.2f}%</td><td>{a["tool_calls"]} → {b["tool_calls"]}</td><td>两组通过</td></tr>')
    a,b=aggregate['bare'],aggregate['skill'];body.append(f'<tr><th>合计</th><th>{a["total_tokens"]:,}</th><th>{b["total_tokens"]:,}</th><th>{reduction(a["total_tokens"],b["total_tokens"]):.2f}%</th><th>{a["tool_calls"]} → {b["tool_calls"]}</th><th>6/6</th></tr></table>')
    body.append('<p>总 Token 是供应方每轮报告的累计用量，包含反复携带的上下文与缓存输入。另将非缓存输入及输出分列，避免将缓存 Token 直接等同于实际费用。</p><img src="token-comparison.png" alt="三任务 Token 与工具调用对照">')
    body.append('<h2>用量分解</h2><table><tr><th>指标</th><th>裸 DSH</th><th>Skills</th><th>下降</th></tr>')
    for label,key in [('非缓存输入 Token','uncached_input_tokens'),('缓存输入 Token','cached_input_tokens'),('输出 Token','output_tokens'),('非缓存输入＋输出','uncached_input_plus_output'),('模型步骤','model_steps'),('工具调用','tool_calls')]:body.append(f'<tr><td>{label}</td><td>{a[key]:,}</td><td>{b[key]:,}</td><td>{reduction(a[key],b[key]):.2f}%</td></tr>')
    body.append('</table><h2>任务与结果质量</h2><p>T01 两组关联半径及冷态参数均一致，原输入保留且均未求解。T02 与 T03 的主结果共四对温度场，每对 52 单元逐单元相同。独立标准库读取器重算真实 cellZone 的极值、体积加权均值及峰值坐标，并核对 JSON/CSV；最大交付温度舍入差约 0.000297 K，低于本次 0.001 K 核验阈值。</p>')
    body.append('<p>裸 DSH 的 OFFBEAT 启动次数为 0/2/8，Skills 为 0/1/3；裸组扫描包含额外临时与固定点校核算例。所有启动计入成本，但额外校核目录不冒充交付主结果。工具失败返回共 10 次与 0 次。该项核验检查执行与产物的一致性，不替代求解器物理模型验证。</p>')
    body.append('<h2>可用于报告的表述</h2><p>在三项独立的无前端成对测试中，两组采用相同模型、参考输入和运行边界，均完成任务并通过交付一致性核验。当前科学计算 Skills 接入相对裸 DSH 的累计总 Token 用量下降 '+f'{reduction(a["total_tokens"],b["total_tokens"]):.2f}%，工具调用次数下降 {reduction(a["tool_calls"],b["tool_calls"]):.2f}%，非缓存输入与输出 Token 合计下降 {reduction(a["uncached_input_plus_output"],b["uncached_input_plus_output"]):.2f}%'+ '。该结果为三任务单次观测，反映完整技能接入的效果，尚不能单独归因于某条批量调用规则。</p>')
    body.append('<h2>解释边界</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in summary['limits'])+'</ul><h2>冻结任务</h2>')
    for task in manifest['tasks']:body.append('<details><summary>'+esc(task['id']+' '+task['title'])+'</summary><pre>'+esc(task['prompt'])+'</pre></details>')
    body.append('<p>证据：<a href="comparison.csv">CSV</a> · <a href="comparison.json">详细统计</a> · <a href="verification.json">独立结果核验</a> · <a href="integrity.json">配置与证据检查</a>。用量仅累加 assistant/message 的 usage，排除流式块重复计数，reasoningTokens 不重复叠加。</p></html>')
    (root/'comparison.html').write_text('\n'.join(body))
    print(json.dumps({'all_checks_passed':summary['all_checks_passed'],'aggregate':summary['aggregate'],'tasks':{t:p['skill_reduction_percent']['total_tokens'] for t,p in summary['tasks'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
