"""Provider-reported cache rates after excluding each session's first request."""
import argparse,csv,html,json
from collections import Counter
from pathlib import Path

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def rates(counts):
    result=dict(counts);inputs=counts['cached_input_tokens']+counts['uncached_input_tokens'];result['input_tokens']=inputs
    result['token_weighted_hit_percent']=100*counts['cached_input_tokens']/inputs if inputs else None
    result['requests_with_cache_percent']=100*counts['requests_with_cache']/counts['requests'] if counts['requests'] else None
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);args=parser.parse_args();root=args.run_root.resolve();comparison=json.loads((root/'comparison.json').read_text());detail=[];tasks={};totals={arm:Counter() for arm in ['bare','skill']}
    for tid,pair in comparison['tasks'].items():
        tasks[tid]={'title':pair['title'],'arms':{}}
        for arm in ['bare','skill']:
            counts=Counter();all_usage=Counter();first=[]
            for path in sorted((root/tid/arm/'traces').rglob('session.jsonl')):
                header={};request=0
                with path.open() as stream:
                    for line in stream:
                        event=json.loads(line)
                        if event.get('type')=='session':header=event;continue
                        if event.get('seq',0)<header.get('seedLength',0) or event.get('type')!='assistant/message':continue
                        data=event.get('data',{});usage=data.get('usage')
                        if not isinstance(usage,dict):raise ValueError('Assistant message without usage')
                        cached=usage['cacheReadTokens'];uncached=usage['inputTokens'];output=usage['outputTokens'];assert usage['totalTokens']==cached+uncached+output
                        request+=1;excluded=request==1
                        row={'task_id':tid,'arm':arm,'session_id':header.get('id',path.parent.name),'request_index_in_session':request,'turn':data.get('turn'),'step':data.get('step'),'excluded_first_request':excluded,'uncached_input_tokens':uncached,'cached_input_tokens':cached,'input_tokens':cached+uncached,'output_tokens':output,'token_cache_hit_percent':100*cached/(cached+uncached) if cached+uncached else None}
                        detail.append(row);all_usage.update(cached_input_tokens=cached,uncached_input_tokens=uncached,output_tokens=output,total_tokens=usage['totalTokens'])
                        if excluded:first.append(row)
                        else:counts.update(requests=1,requests_with_cache=int(cached>0),cached_input_tokens=cached,uncached_input_tokens=uncached,output_tokens=output)
            for key in ['total_tokens','cached_input_tokens','uncached_input_tokens','output_tokens']:assert all_usage[key]==pair['arms'][arm][key],(tid,arm,key)
            result=rates(counts);result['excluded_first_requests']=len(first);result['first_request_usage']=first;tasks[tid]['arms'][arm]=result;totals[arm].update(counts)
    output={'definition':'Within each independent session, exclude the first new assistant/message carrying usage (the first successful model request). Cache hit rate = sum(cacheReadTokens) / sum(cacheReadTokens + inputTokens), excluding output tokens. Aggregate is token-weighted, not an arithmetic mean of request or task percentages.','cache_provenance_limit':'The provider usage identifies cached tokens but not who originally populated the cache. After-first requests are the measurement window; strict same-session cache provenance cannot be established from these logs.','tasks':tasks,'aggregate':{arm:rates(counts) for arm,counts in totals.items()}}
    output['aggregate']['skill_minus_bare_percentage_points']=output['aggregate']['skill']['token_weighted_hit_percent']-output['aggregate']['bare']['token_weighted_hit_percent']
    output['aggregate']['excluded_first_requests']=sum(v['arms'][a]['excluded_first_requests'] for v in tasks.values() for a in ['bare','skill'])
    save(root/'cache-comparison.json',output)
    columns=['task_id','title','arm','requests','requests_with_cache','cached_input_tokens','uncached_input_tokens','input_tokens','token_weighted_hit_percent','requests_with_cache_percent']
    with (root/'cache-comparison.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for tid,pair in tasks.items():
            for arm,value in pair['arms'].items():writer.writerow({k:({'task_id':tid,'title':pair['title'],'arm':arm,**value}).get(k) for k in columns})
        for arm in ['bare','skill']:writer.writerow({k:({'task_id':'TOTAL','title':'合计（排除各会话首次）','arm':arm,**output['aggregate'][arm]}).get(k) for k in columns})
    with (root/'cache-per-request.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(detail[0]));writer.writeheader();writer.writerows(detail)
    body=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>排除首次请求后的缓存命中率</title><style>body{max-width:1000px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui;color:#172333}table{border-collapse:collapse;width:100%;margin:24px 0}th,td{padding:9px 12px;border:1px solid #dce3eb;text-align:right}th:first-child,td:first-child{text-align:left}code{background:#eef2f7;padding:3px 6px}a{color:#245ba6}</style><h1>排除首次请求后的缓存命中率</h1><p>每个独立会话剔除第一次模型请求，共剔除 6 次。按后续请求的输入 Token 加权统计，输出 Token 不进入命中率分母。</p><p><code>命中率 = 缓存读取 Token 合计 ÷（缓存读取＋非缓存输入 Token 合计）</code></p><table><tr><th>任务</th><th>裸 DSH</th><th>科学计算 Skills</th><th>后续请求数 裸 / Skills</th></tr>']
    for tid,pair in tasks.items():
        a,b=pair['arms']['bare'],pair['arms']['skill'];body.append(f'<tr><td>{tid} {html.escape(pair["title"])}</td><td>{a["token_weighted_hit_percent"]:.2f}%</td><td>{b["token_weighted_hit_percent"]:.2f}%</td><td>{a["requests"]} / {b["requests"]}</td></tr>')
    a,b=output['aggregate']['bare'],output['aggregate']['skill'];body.append(f'<tr><th>合计（Token 加权）</th><th>{a["token_weighted_hit_percent"]:.2f}%</th><th>{b["token_weighted_hit_percent"]:.2f}%</th><th>{a["requests"]} / {b["requests"]}</th></tr></table>')
    body.append(f'<p>有缓存命中的请求占比，两组均为 100%：裸 DSH {a["requests_with_cache"]}/{a["requests"]}，Skills {b["requests_with_cache"]}/{b["requests"]}。有命中不代表整次请求的输入全部命中。</p><p>裸 DSH：缓存输入 {a["cached_input_tokens"]:,}，非缓存输入 {a["uncached_input_tokens"]:,}。Skills：缓存输入 {b["cached_input_tokens"]:,}，非缓存输入 {b["uncached_input_tokens"]:,}。</p><p>本轮 Skills 的 Token 加权缓存命中率低约 {a["token_weighted_hit_percent"]-b["token_weighted_hit_percent"]:.2f} 个百分点，同时总请求轮次与累计上下文输入更少。前述 Token 用量下降不能解释为缓存命中率上升。</p><p>这里“任务内”指排除首请求后的统计窗口。usage 无法区分缓存由本会话还是其他会话写入；本结果仍为三个任务每组各一次的观测。</p><p><a href="cache-comparison.csv">汇总 CSV</a> · <a href="cache-per-request.csv">逐请求明细 CSV（含首请求及剔除标记）</a> · <a href="cache-comparison.json">JSON</a> · <a href="comparison.html">原 Token 对比报告</a></p></html>')
    (root/'cache-comparison.html').write_text('\n'.join(body))
    print(json.dumps({'tasks':{tid:{arm:value['token_weighted_hit_percent'] for arm,value in pair['arms'].items()} for tid,pair in tasks.items()},'aggregate':output['aggregate'],'rows':len(detail)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
