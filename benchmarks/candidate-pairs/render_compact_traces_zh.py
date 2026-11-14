#!/usr/bin/env python3
"""Publish one-line Chinese tool events, preserving raw evidence separately."""
import argparse
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

helper=module('chinese_trace_helpers','translate_traces_zh.py')
compact=module('compact_chinese_helpers','compact_traces_zh.py')

def load(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def parameters(call,workspace,root):
    if call['tool']=='todo_write':
        entries=call['args'].get('todos',[]);entries=json.loads(entries) if isinstance(entries,str) else entries
        return {'待办':[{'任务':f'条目{i+1}','状态':helper.TODO_STATUS[e['status']]} for i,e in enumerate(entries)]}
    return helper.params_view(call,{},workspace,root)[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);parser.add_argument('--translations',type=Path,default=HERE/'trace-descriptions.zh.json');args=parser.parse_args();root=args.run_root.resolve()
    translations=load(args.translations);manifest=load(root/'manifest.json');missing=set();inputs={};sources={}
    for task in manifest['tasks']:
        for arm in manifest.get('arms',['bare','skill']):
            folder=root/task['id']/arm;trace_files=list((folder/'traces').rglob('session.jsonl'));assert len(trace_files)==1
            trace=trace_files[0];calls,steps=helper.read_session(trace);inputs[(task['id'],arm)]=(trace,calls,steps)
            sources[str(trace.relative_to(root))]=sha(trace)
            for c in calls:
                if c['tool']=='bash' and c['args'].get('description') not in translations:
                    description=c['args'].get('description','')
                    if not re.search(r'[\u4e00-\u9fff]',description):missing.add(description)
    if missing:
        save(root/'待翻译动作.json',sorted(missing));print(json.dumps({'missing':len(missing),'file':str(root/'待翻译动作.json')},ensure_ascii=False));raise SystemExit(2)
    comparison=load(root/'comparison.json');verified=load(root/'verification.json');destination=root/'中文单行轨迹';destination.mkdir(exist_ok=True);dataset=[];docs=[]
    arms=manifest.get('arms',['bare','skill']);count=len(arms)*len(manifest['tasks']);combined_name='六次运行_一行事件汇总.md' if count==6 else '本轮运行_一行事件汇总.md'
    combined=[f'# 本轮{count}次运行 一行事件汇总','','每行一个工具调用及其结果；北京时间。R为原模型轮次，仅在异常、重试或明显耗时时追加说明。','']
    index=[f'# 本轮{count}次运行的中文单行轨迹','',f'[合并查看本轮全部运行]({combined_name})','','一行对应一个工具调用及其结果；R为模型轮次。同轮多个工具依次列出，未将其视作并行。无异常时省略重复的返回说明；完整参数与原始行号保存在中文工具记录中。','','| 题目 | '+' | '.join('裸DSH' if arm=='bare' else 'Skill' for arm in arms)+' |','|'+'---|'*(len(arms)+1)]
    for task in manifest['tasks']:
        tid=task['id'];links=[]
        for arm in arms:
            group='裸DSH' if arm=='bare' else 'Skill'
            trace,calls,steps=inputs[(tid,arm)];workspace=root/tid/arm/'workspace';stats=comparison['tasks'][tid][arm];actual=verified['tasks'][tid][arm]
            assert len(calls)==stats['tool_calls'];assert all(c['result_line'] for c in calls)
            lines=[]
            for number,c in enumerate(calls,1):
                if c['tool']=='bash':
                    raw=c['args'].get('description','');action=translations.get(raw,raw)
                else:action=helper.translated_action(c,translations,{},workspace,root)
                summary,notes=helper.return_summary(c)
                row={'任务':tid,'组别':group,'动作序号':number,'模型轮次':c['step'],'发起时间_北京时间':helper.local_time(c['started_ms']),'记录间隔秒':round((c['ended_ms']-c['started_ms'])/1000,3),'工具':c['tool'],'中文动作':action,'参数':parameters(c,workspace,root),'中文返回摘要':summary,'关键输出片段':helper.key_output(c),'中文诊断':notes,'原始定位':{'文件':str(trace.relative_to(root)),'调用行':c['call_line'],'返回行':c['result_line'],'调用事件序号':c['call_seq'],'返回事件序号':c['result_seq'],'调用ID':c['id']}}
                dataset.append(row);lines.append(compact.event_line(row))
            name=f'{tid}_{group}_一行轨迹.md';title=f'{tid} {group}';intro=f'{stats["wall_seconds"]:.1f}秒｜{len(lines)}条工具事件｜{len(steps)}轮｜真实启动{actual["solver_starts"]}次｜{helper.STATUS[actual["status"]]}'
            text='\n'.join([f'# {title} 一行轨迹','',intro,'','```text',*lines,'```',''])
            (destination/name).write_text(text);combined += [f'## {title}','',intro,'','```text',*lines,'```',''];links.append(f'[{len(lines)}行]({name})')
            docs.append({'任务':tid,'组别':group,'文件':name,'事件数':len(lines),'模型轮次':len(steps),'SHA256':sha(destination/name)})
        index.append('| '+tid+' | '+' | '.join(links)+' |')
    with (destination/'工具调用中文记录.jsonl').open('w') as stream:
        for row in dataset:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    combined[2]=combined[2]+f' 共{len(dataset)}行事件。'
    index+=['',f'共{len(dataset)}条工具调用。只翻译可观察动作及返回摘要，不包含模型内部推理正文。命令和变量原名保留。原始日志未改动，也没有为翻译再次运行模型或求解器。','','[机器可读中文记录](工具调用中文记录.jsonl)｜[来源与数量核对](翻译清单.json)｜[本轮结果](../结果汇总.md)']
    (destination/combined_name).write_text('\n'.join(combined));(destination/'总索引.md').write_text('\n'.join(index)+'\n')
    assert all(sha(root/path)==value for path,value in sources.items())
    save(destination/'翻译清单.json',{'生成时间_北京时间':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'事件总数':len(dataset),'文档':docs,'源文件SHA256':sources,'原始轨迹保持不变':True,'翻译字典SHA256':sha(args.translations)})
    print(json.dumps({'documents':len(docs),'events':len(dataset),'destination':str(destination)},ensure_ascii=False))


if __name__=='__main__':main()
