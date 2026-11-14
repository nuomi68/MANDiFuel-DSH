#!/usr/bin/env python3
"""Classify observable probe/read attempts, never private model reasoning."""
import argparse
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


def read_calls(folder):
    calls=[]
    for path in (folder/'traces').rglob('session.jsonl'):
        for line in path.open():
            event=json.loads(line)
            if event.get('type')!='tool/call':continue
            d=event['data'];a=d.get('arguments',{})
            if isinstance(a,str):a=json.loads(a)
            calls.append({'step':d['step'],'tool':d['name'],'arguments':a,'time_ms':event['time'],'call_id':d['callId']})
    return calls


def categories(c):
    a=c['arguments'];tool=c['tool'];command=str(a.get('command',''));file=str(a.get('file_path',''));text=command+' '+file;found=[]
    if tool=='web_fetch':
        url=unquote(str(a.get('url','')))
        if re.search(r'\.(?:C|H|cpp|hpp)(?:/raw|[?&#]|$)',url):
            found.append('solver_source_content')
        elif ('repository/tree' in url or '/tree/' in url) and re.search(r'offbeatLib|/src|path=src',url):
            found.append('solver_source_discovery')
        else:
            found.append('public_document_lookup')
    elif tool=='web_search':found.append('public_document_lookup')
    cpp=bool(re.search(r'\.(?:C|H|cpp|hpp|cxx|hxx)(?:[\s\"\';,:]|$)',text))
    solver_path=bool(re.search(r'/offbeat/(?:offbeatLib|offbeat)(?:/|\b)|OpenFOAM[^\s\"\']*/src(?:/|\b)|\$WM_PROJECT_DIR/src|\$FOAM_SRC',text))
    content=bool(re.search(r'(?:^|[;\n|&])\s*(?:cat|sed|grep|less|more)\b',command)) or bool(re.search(r'\b(?:head|tail)\s+[^\n;]*\.(?:C|H|cpp|hpp)',command)) or 'read_text(' in command or 'inspect.getsource' in command
    discovery=bool(re.search(r'(?:^|[;\n|&])\s*(?:find|ls)\b',command))
    if tool=='read' and cpp:found.append('solver_source_content')
    elif tool=='bash' and solver_path:
        if content:found.append('solver_source_content')
        elif discovery:found.append('solver_source_discovery')
    elif tool=='bash' and discovery and cpp:found.append('solver_source_discovery')
    probe=bool(re.search(r'(?:^|[;\n|&])\s*(?:env|printenv|which|ldd|strings)\b|\bcommand\s+-v\b|\b(?:offbeat|blockMesh|checkMesh)\s+(?:--?help|--?version)\b',command))
    install_discovery=discovery and bool(re.search(r'/home/lwz/OpenFOAM|\$MANDIFUEL_OFFBEAT_BIN|/platforms/[^\s]*/bin',command)) and not solver_path
    if tool=='bash' and (probe or install_discovery):found.append('environment_probe')
    plugin_python=bool(re.search(r'(?:frozen-plugin|\$MANDIFUEL_PLUGIN_ROOT|PLUGIN)[^\n;]*(?:/lib/|(?:result_api|openfoam_parser|case_runner|study_runner|foam_edit)\.py)|/skills/[^\s]+/scripts/[^\s]+\.py',text))
    if plugin_python and ((tool=='read') or (tool=='bash' and content and not (command.lstrip().startswith('python') and not re.search(r'(?:^|[;\n])\s*(?:cat|sed|grep)\b',command)))):found.append('plugin_implementation_read')
    if re.search(r'launch-config|instrumented-bin/(?:offbeat|config.json)|/(?:preflight|boot|toolchain)\.(?:json|stdout|stderr)',text) and (tool=='read' or content):found.append('instrumentation_inspection')
    return sorted(set(found))


def audit(root):
    manifest=json.loads((root/'manifest.json').read_text());result={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'rule_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'count_unit':'工具参数中可观察的探测/查看尝试，不是实际文件IO次数；诊断不作结果评分','overlap':'分类允许重叠，不把各类计数相加为独立总数','tasks':{}}
    names=['environment_probe','solver_source_content','solver_source_discovery','plugin_implementation_read','instrumentation_inspection','public_document_lookup']
    for task in manifest['tasks']:
        tid=task['id'];result['tasks'][tid]={}
        for arm in manifest.get('arms',['bare','skill']):
            folder=root/tid/arm;workspace=folder/'workspace';starts=workspace/'solver-starts.jsonl'
            executions=[json.loads(x) for x in starts.read_text().splitlines()] if starts.exists() else []
            first=min((datetime.fromisoformat(e['started_at_utc']).timestamp()*1000 for e in executions),default=None)
            before=Counter();after=Counter();hits=[];skills=[];total=0
            for c in read_calls(folder):
                total+=1
                if c['tool']=='skill':skills.append({'step':c['step'],'name':c['arguments'].get('name',c['arguments'].get('skill'))})
                selected=categories(c)
                if not selected:continue
                early=first is None or c['time_ms']<first
                (before if early else after).update(selected)
                a=c['arguments']
                hits.append({'step':c['step'],'tool':c['tool'],'call_id':c['call_id'],'categories':selected,'before_first_solve_or_prepare_only':early,'description':a.get('description'),'file_path':a.get('file_path'),'command':a.get('command'),'url':a.get('url'),'transport':'web' if c['tool'] in ['web_fetch','web_search'] else 'local'})
            result['tasks'][tid][arm]={'window':'whole preparation task' if first is None else 'before first actual solver start','tool_calls':total,'before_counts':{n:before[n] for n in names},'after_counts':{n:after[n] for n in names},'skill_loads':skills,'classified_calls':hits}
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);parser.add_argument('--old-run',type=Path);args=parser.parse_args();root=args.run_root.resolve()
    result={'current':audit(root)}
    if args.old_run:result['old']=audit(args.old_run.resolve())
    (root/'workflow-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({tid:{arm:v['before_counts'] for arm,v in arms.items()} for tid,arms in result['current']['tasks'].items()},ensure_ascii=False))


if __name__=='__main__':main()
