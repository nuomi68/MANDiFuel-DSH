#!/usr/bin/env python3
"""Export complete observable tool trajectories as Chinese reading copies.

Reads only tool/call, tool/result and step/start events for publication. Never
exports assistant messages, chunks, system prompt bodies or model reasoning.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ZH=ZoneInfo('Asia/Shanghai')
TOOLS={'bash':'执行命令','read':'读取文件','write':'写入文件','edit':'修改文件','skill':'加载技能','todo_write':'更新待办清单','job_output':'读取后台作业输出','job_list':'列出后台作业','web_search':'搜索网页','web_fetch':'读取网页'}
SKILLS={'prepare-offbeat-case':'输入准备','execute-offbeat-case':'算例执行','extract-offbeat-results':'结果提取','orchestrate-offbeat-study':'研究规划','conduct-offbeat-study':'研究执行'}
STATUS={'prepared':'输入准备完成','completed':'计算及交付完成','partial':'部分完成','incomplete':'未完成'}
TODO_STATUS={'pending':'待执行','in_progress':'进行中','completed':'已完成'}
TASK_NAMES={'P02':'尺寸修改与输入准备','C04':'腐蚀氧化层计算','W01':'连续计算和分段续算'}


def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def local_time(stamp):
    value=datetime.fromtimestamp(stamp/1000,ZH) if isinstance(stamp,(int,float)) else datetime.fromisoformat(stamp).astimezone(ZH)
    return value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
def clean(value):
    text=str(value)
    text=re.sub(r'(?i)\b(?:sk-proj|sk)-[a-z0-9_-]{12,}','<敏感值已隐藏>',text)
    text=re.sub(r'(?i)(bearer\s+)[^\s\"\']+',r'\1<敏感值已隐藏>',text)
    text=re.sub(r'(?i)((?:api[_-]?key|password|access[_-]?token)\s*[=:]\s*)[\"\']?[^\s,;\"\']{12,}',r'\1<敏感值已隐藏>',text)
    return text

def text_blocks(content):
    for block in content if isinstance(content,list) else []:
        if block.get('type')=='text': yield block.get('text','')
        elif block.get('type')=='tool-result': yield from text_blocks(block.get('content',[]))

def tool_error(content):
    return any(b.get('isError') is True or (b.get('type')=='tool-result' and tool_error(b.get('content',[]))) for b in content if isinstance(b,dict))

def short_path(path,workspace,root):
    for base,prefix in [(workspace,''),(root,'实验目录/')]:
        try: return prefix+str(Path(path).relative_to(base))
        except ValueError: pass
    return str(path)

def fenced(text,kind='text'):
    longest=max((len(m.group()) for m in re.finditer(r'`+',text)),default=0)
    fence='`'*max(3,longest+1)
    return fence+kind+'\n'+text.rstrip()+'\n'+fence

def read_session(path):
    calls=[]; by_id={}; steps={}
    for line_number,line in enumerate(path.open(),1):
        event=json.loads(line); kind=event.get('type'); data=event.get('data',{})
        if kind=='step/start': steps[data['step']]=event.get('time')
        elif kind=='tool/call':
            args=data.get('arguments',{})
            if isinstance(args,str): args=json.loads(args)
            call={'id':data['callId'],'step':data['step'],'tool':data['name'],'args':args,'started_ms':event.get('time'),'call_seq':event.get('seq'),'call_line':line_number,'trace':path,'result_line':None}
            calls.append(call);by_id[call['id']]=call
        elif kind=='tool/result':
            message=data.get('message',{}); call=by_id.get(message.get('source',{}).get('callId'))
            if call is None: raise ValueError('Unmatched tool result')
            content=message.get('content',[])
            call.update(result_line=line_number,result_seq=event.get('seq'),ended_ms=event.get('time'),output='\n'.join(text_blocks(content)),tool_error=bool(data.get('error')) or tool_error(content))
    return calls,steps

def translated_action(call,translations,todos,workspace,root):
    tool=call['tool'];a=call['args']
    if tool=='bash': return translations[a['description']]
    if tool in ['read','write','edit']:
        verb={'read':'读取','write':'写入','edit':'修改'}[tool]
        return verb+' `'+short_path(a['file_path'],workspace,root)+'`'
    if tool=='skill':
        name=a.get('name',a.get('skill')); return '加载'+SKILLS.get(name,'指定')+'技能 `'+name+'`'
    if tool=='todo_write':return '更新任务待办清单'
    if tool=='job_output':return '读取后台作业 `'+str(a.get('job_id'))+'` 的输出'
    if tool=='job_list':return '列出当前后台作业及其状态'
    if tool=='web_search':return '搜索公开网页，查找命令中列出的信息'
    if tool=='web_fetch':return '尝试读取指定网页的内容'
    raise ValueError('Untranslated tool '+tool)


def diagnostics(call):
    text=call.get('output',''); out=[]
    # A tool may have printed its own raw session. Do not quote or interpret that
    # body, because it can contain private model message material.
    if re.search(r'"type"\s*:\s*"(?:assistant/chunk|assistant/message|request/context)"|<think>|"reasoningContent"',text):
        return ['返回内容涉及会话记录；仅保留此次查看动作及原始位置，不展开其中的模型消息。']
    timeout=re.search(r'\[timed out after (\d+)ms\]',text)
    if timeout:out.append('工具前台命令超时：'+str(int(timeout[1])/1000)+'秒；命令被终止，不能当作成功或仍在后台运行。')
    signal=re.search(r'\[killed by signal:\s*([^\]]+)\]',text)
    if signal:out.append('工具命令被信号终止：'+signal[1]+'。')
    if 'edit requires reading' in text:out.append('编辑工具要求先读取该文件，本次修改未执行；需读取后重试。')
    if 'file changed since it was read' in text:out.append('文件自上次读取后已变化；本次写入或修改被拒绝，需重新读取后重试。')
    if 'web fetch failed' in text:out.append('网页读取失败，网络请求未取得正文。')
    if 'Traceback (most recent call last)' in text:
        out.append('输出含 Python 异常回溯；工具返回或管道退出码为 0 时，也不能据此认为提取或脚本成功。')
        if 'incomplete reciprocal metadata' in text:out.append('解析器错误：fuelOuter 边界缺少完整的双向对应元数据。')
        if 'no numeric directories below' in text:out.append('解析器错误：指定目录下未发现数值时间目录。')
        for typ,zh in [('FileNotFoundError','文件不存在'),('PermissionError','访问被拒绝'),('ModuleNotFoundError','Python 模块不存在'),('KeyError','缺少字典键'),('ValueError','数值或参数不合法'),('TypeError','数据类型不符合要求')]:
            matches=re.findall(r'^'+typ+r':\s*(.*)$',text,re.M)
            if matches:
                last=matches[-1]
                if typ=='KeyError':out.append(zh+'：`'+clean(last)[:160]+'`。')
                elif typ=='ModuleNotFoundError':out.append(zh+'：`'+clean(last)[:160]+'`。')
                elif typ in ['FileNotFoundError','PermissionError']:
                    quoted=re.findall(r"['\"]([^'\"]+)['\"]",last)
                    out.append(zh+('：`'+clean(quoted[-1])+'`。' if quoted else '。'))
                else:out.append(zh+'；原始回溯见返回记录。')
    if 'FOAM FATAL' in text and not re.search(r'"(?:before_state|executions|physical_times_s)"',text):
        if 'attempt to read beyond EOF' in text:
            out.append('返回日志包含 OpenFOAM 致命读取错误：读取 D 边界的 coolantPressureList 时提前到达文件尾。查看旧日志本身不等于再次求解失败。')
        else:out.append('返回内容包含 OpenFOAM 致命错误文本；需结合下方真实启动表区分当前运行、旧日志或源码内容。')
    denied=[]
    for line in text.splitlines():
        if ('Permission denied' in line or 'permission denied' in line or 'EACCES' in line) and '.bashrc' not in line:
            paths=re.findall(r"['\"](/[^'\"]+)['\"]",line)
            denied.extend(paths)
    denied=list(dict.fromkeys(denied))
    if denied:out.append('输出中的访问被拒绝路径：'+ '、'.join('`'+clean(p)+'`' for p in denied[:3])+('等' if len(denied)>3 else '')+'。')
    elif any(('Permission denied' in x or 'EACCES' in x) and '.bashrc' not in x for x in text.splitlines()):out.append('输出包含读取权限拒绝信息。')
    missing=[]
    for line in text.splitlines():
        if 'No such file or directory' in line:
            paths=re.findall(r"['\"](/[^'\"]+)['\"]",line)
            missing.extend(paths)
    if missing:out.append('输出中提示路径不存在：'+'、'.join('`'+clean(p)+'`' for p in list(dict.fromkeys(missing))[:3])+'。')
    if 'FOAM Warning' in text:out.append('返回内容中含 OpenFOAM 警告；可能来自当前日志或被查看的源码，不自动计作一次求解失败。')
    return list(dict.fromkeys(out))


def return_summary(call):
    tool=call['tool'];a=call['args'];text=call.get('output','')
    if call['result_line'] is None:return '未找到对应返回记录。',[]
    status='工具明确报告异常' if call.get('tool_error') else '工具已返回，未设置工具异常标记'
    codes=re.findall(r'\[exit code:\s*(-?\d+)\]|\[status:\s*[^\]]*?exit code:\s*(-?\d+)\]',text)
    codes=list(dict.fromkeys(int(x or y) for x,y in codes))
    if codes:status+='；输出显式标出的退出码为 '+', '.join(map(str,codes))
    notes=diagnostics(call)
    if re.search(r'\bstatus:\s*running\b',text):notes.append('后台作业仍在运行，本次只返回阶段性输出。')
    if re.search(r'\bstatus:\s*completed\b',text):notes.append('后台作业已结束；仍需检查其日志及脚本异常。')
    if 1 in codes and tool=='bash' and re.search(r'\bdiff\b',a.get('command','')):notes.append('本命令包含 diff；退出码 1 也可能仅表示发现差异，不直接等于工程计算失败。')
    if 1 in codes and tool=='bash' and re.search(r'\bgrep\b',a.get('command','')):notes.append('本命令包含 grep；退出码 1 也可能表示没有匹配项。')
    meaningful=[x for x in text.splitlines() if x.strip() and not x.startswith('[stderr]') and 'landlock-run: partial enforcement' not in x and not ('.bashrc' in x and 'Permission denied' in x)]
    if tool=='read':
        numbered=re.findall(r'^([0-9]+):',text,re.M)
        detail=('；显示文件第 '+numbered[0]+'—'+numbered[-1]+' 行' if numbered else '；返回文件读取内容')
    elif tool in ['write','edit']:
        if call.get('tool_error'):detail='；这次文件操作被拒绝'
        elif 'Created file' in text:detail='；返回内容确认已创建文件'
        elif 'Updated file' in text or 'Modified file' in text:detail='；返回内容确认已更新文件'
        else:detail='；返回文件操作结果，原始文件位置见参数'
    elif tool=='skill':detail='；返回技能说明及资源路径'
    elif tool=='todo_write':
        m=re.search(r'(\d+) pending, (\d+) in progress, (\d+) completed',text)
        detail=('；待执行 '+m[1]+' 项、进行中 '+m[2]+' 项、已完成 '+m[3]+' 项' if m else '；返回待办清单更新结果')
    elif tool=='web_search':
        n=len(re.findall(r'^- \[',text,re.M));detail='；返回 '+str(n)+' 条网页来源链接'
    elif tool=='web_fetch':detail='；返回网页读取结果'
    elif tool=='job_list':detail='；返回 '+str(len(re.findall(r'^bash-\d+',text,re.M)))+' 个后台作业条目'
    else:detail='；返回 '+str(len(meaningful))+' 行非空输出（扣除重复的 shell 初始化提示）'
    if tool in ['bash','job_output'] and not any('会话记录' in n for n in notes):
        times=re.findall(r'^Time\s*=\s*([-+\d.eE]+)\s*(days|seconds|hours|years)?',text,re.M)
        if times:
            value,unit=times[-1];detail+='；所显示日志的最后一条模型时间为 '+value+{'days':' 天','seconds':' 秒','hours':' 小时','years':' 年','':'（原文未标单位）'}.get(unit,'')
        if 'Mesh OK' in text:detail+='；输出含“网格检查通过”标记'
        runtimes=re.findall(r'^real\s+(\d+)m([\d.]+)s',text,re.M)
        if runtimes:detail+='；shell 计时为 '+runtimes[-1][0]+' 分 '+runtimes[-1][1]+' 秒'
    return status+detail+'。',notes


def key_output(call):
    text=call.get('output','')
    if re.search(r'"type"\s*:\s*"(?:assistant/chunk|assistant/message|request/context)"|<think>|"reasoningContent"',text): return []
    if call['tool']=='web_search':
        return ['来源链接：'+url for url in re.findall(r'^- \[.*?\]\((https?://[^)]+)\)',text,re.M)[:8]]
    if call['tool'] not in ['bash','job_output','read']:return []
    fields=r'rOuterFuel|rInnerClad|rOuterClad|DiamCold|GapCold|endTime|deltaT|timePrecision|writePrecision|writeInterval|writeFormat|startFrom|startTime|thermalSolver|mechanicsSolver|neutronicsSolver|heatSource|burnup|fastFlux|gapGas|fgr|corrosion|mean_m|mean_um|final_time_s|final_physical_seconds|exit_code|solver_steps'
    selected=[]
    for raw in text.splitlines():
        line=re.sub(r'^\s*\d+:\s*','',raw).strip()
        if re.match(r'^[\"\']?(?:'+fields+r')[\"\']?\s*(?::|=|\s)\s*',line) and len(line)<=200:
            if '"' in line or "'" in line or re.search(r'\d|none|fromLatestTime|ascii|latestTime|startTime',line):selected.append(line)
        elif call['tool']=='bash' and re.fullmatch(r'[-+0-9.eE\s(),;]+',line) and re.search(r'\d',line) and len(line)<100:
            selected.append(line)
    return ['输出中的配置或数值片段：`'+clean(x).replace('`',"'")+'`。' for x in list(dict.fromkeys(selected))[:6]]


def params_view(call,todos,workspace,root):
    a=call['args'];tool=call['tool'];lines=[]
    if tool=='bash':return fenced(clean(a['command']),'bash'),{'命令原文':clean(a['command']),'说明原文':a['description']}
    if tool in ['read','write','edit']:
        path=Path(a['file_path']); shown=short_path(path,workspace,root)
        lines+=['文件：`'+shown+'`。']
        if path.exists():lines+=['[打开当前保留的文件]('+str(path)+')。']
        record={'文件路径':str(path)}
        if tool=='read':
            for key,word in [('offset','起始偏移'),('limit','读取上限')]:
                if key in a:lines.append(word+'：'+str(a[key])+'。');record[word]=a[key]
        elif tool=='write':
            record['写入字符数']=len(a.get('content',''));lines.append('本次提交写入 '+str(record['写入字符数'])+' 个字符。正文保留在原始写入记录中，不在此重复大段代码或报告。')
        else:
            old=clean(a.get('old_string',''));new=clean(a.get('new_string',''))
            record.update(原片段=old,新片段=new)
            lines+=['原片段：',fenced(old),'新片段：',fenced(new)]
        return '\n\n'.join(lines),record
    if tool=='skill':
        name=a.get('name',a.get('skill'));return '技能：'+SKILLS.get(name,'')+' `'+name+'`。',{'技能':name}
    if tool=='todo_write':
        entries=a.get('todos',[]);entries=json.loads(entries) if isinstance(entries,str) else entries
        translated=[{'任务':todos[t['content']],'状态':TODO_STATUS[t['status']]} for t in entries]
        return '\n'.join('- '+e['状态']+'：'+e['任务'] for e in translated),{'待办':translated}
    if tool=='web_search':return '\n'.join('- 查询原文：`'+clean(q)+'`' for q in a.get('queries',[])),{'查询原文':[clean(q) for q in a.get('queries',[])]}
    if tool=='web_fetch':return '网页地址：`'+clean(a['url'])+'`。',{'网页地址':clean(a['url'])}
    if tool=='job_output':return '后台作业编号：`'+str(a.get('job_id'))+'`。',{'作业编号':a.get('job_id')}
    return '无额外参数。',{}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);args=parser.parse_args();root=args.run_root.resolve()
    translations=load(HERE/'trace-descriptions.zh.json');todos=load(HERE/'trace-todos.zh.json')
    comparison=load(root/'comparison.json');verified=load(root/'verification.json')
    destination=root/'中文详细轨迹';destination.mkdir(exist_ok=True)
    manifest={'生成时间':datetime.now(ZH).isoformat(),'来源运行':str(root),'范围':'六次有效隔离运行的全部工具调用、参数及返回状态；不输出模型内部推理或系统提示正文','文档':[],'源文件SHA256':{},'不同英文动作说明数':len(translations)}
    dataset=[];index=['# 六次运行的中文详细轨迹','','这里对应修正读取隔离后的有效实验，共六次运行、715次工具调用。前面的受污染预跑和启动诊断不混入本组轨迹。','','每份文件按原始模型轮次和调用时间排列，逐条给出中文操作说明、参数或命令原文、中文返回摘要、错误说明和原始记录行号。大段源码、场数据和报告正文不逐字重贴；可沿文件或原始调用定位查看。模型内部推理及系统提示正文不包含在翻译中。','','显示时间统一为北京时间（UTC+8），这六次运行发生于2026年11月13日凌晨。原始JSONL的UTC时间不改动。','','| 任务 | 组别 | 耗时 / 秒 | 模型轮次 | 工具调用 | OFFBEAT启动 | 中文详细轨迹 |','|---|---|---:|---:|---:|---:|---|']
    for tid in ['P02','C04','W01']:
        for arm in ['bare','skill']:
            group='裸DSH' if arm=='bare' else 'Skill';folder=root/tid/arm;workspace=folder/'workspace';trace_files=list((folder/'traces').rglob('session.jsonl'))
            assert len(trace_files)==1
            trace=trace_files[0];fingerprint=sha(trace);manifest['源文件SHA256'][str(trace.relative_to(root))]=fingerprint
            calls,steps=read_session(trace);expected=comparison['tasks'][tid][arm];actual=verified['tasks'][tid][arm];run=actual['run']
            assert len(calls)==expected['tool_calls'] and len(steps)==expected['steps']
            assert all(c['result_line'] is not None for c in calls)
            name=f'{tid}_{group}_逐步中文轨迹.md';path=destination/name;by_step=defaultdict(list);native_files=defaultdict(list)
            for n,call in enumerate(calls,1):
                call['number']=n;by_step[call['step']].append(call)
                if call['tool'] in ['read','edit','write']:native_files[call['args']['file_path']].append((n,call['tool']))
            shell_warning=sum('.bashrc' in c.get('output','') and 'Permission denied' in c.get('output','') for c in calls)
            landlock_warning=sum('landlock-run: partial enforcement' in c.get('output','') for c in calls)
            lines=[f'# {tid} {group} 逐步中文轨迹','',f'任务：{TASK_NAMES[tid]}。交付状态：{STATUS[actual["status"]]}。',f'运行起止：{local_time(run["started_at_utc"])} 至 {local_time(run["ended_at_utc"])}（北京时间）。',f'墙钟耗时 {run["wall_seconds"]:.3f} 秒；{len(steps)} 个模型轮次；{len(calls)} 次工具调用；真实OFFBEAT启动 {actual["solver_starts"]} 次。','', '本文逐条翻译可观察动作与返回含义，不包含模型推理正文。命令、文件名、API名称、变量名及数值保留原样；写入大段文件的正文不重复，改动片段保留。','', '“工具已返回”只说明收到返回，不保证命令、提取脚本或物理计算成功。diff/grep 的非零退出、查看旧失败日志、管道掩盖 Python 异常，分别说明。记录间隔是调用事件到返回事件的时间，不能把所有间隔相加当作墙钟。','',f'重复环境提示：{landlock_warning} 次返回包含旧版 Landlock ABI 的部分限制提示；{shell_warning} 次返回包含读取用户 .bashrc 被拒绝。此类初始化提示统一在这里计数，不逐条复写，也不等同于OFFBEAT失败。','', '## 真实求解器启动记录','', '| 次序 | 算例目录 | 退出码 | 正常终止 | 保存终态的物理秒 | 原始求解日志 |','|---|---|---:|---|---:|---|']
            for n,event in enumerate(actual['executions'],1):
                case=short_path(event['case_root'],workspace,root);log=Path(event['evidence_dir'])/'solver.log'
                lines.append(f'| {n} | `{case}` | {event["exit_code"]} | {"是" if event["normal"] else "否"} | {event["physical_last_time_s"]} | [日志]({log}) |')
            if not actual['executions']:lines.append('| — | 纯输入准备，无真实求解 | — | — | — | — |')
            if tid=='C04' and arm=='skill':lines+=['','两次真实求解均正常终止。第二次为调整时间目录名精度后重新计算，不能记作首次求解失败。']
            if tid=='W01':lines+=['','两组均在第三次启动读取交接位移场 D 的压力表时失败，第四次修复后完成续算。以下读取该失败日志的操作不会额外增加求解器启动次数。']
            if tid=='W01' and arm=='skill':lines+=['','本组显式把任务归为 case，实际加载准备、执行和提取技能。现有协议对物理续算的分类与题库预期存在边界不一致；未使用 Study 本身不作为任务失败。重点可查看提取阶段含 Python 异常回溯的轮次，以及修改后重新执行提取的轮次。']
            if tid=='P02':
                lines+=['', '最终交付参数：燃料外半径4.20 mm，全部对应包壳块内/外半径4.30/4.90 mm；DiamCold=0.0084 m，GapCold=0.0002 m。源输入、轴向结构和其余材料载荷检查通过。']
            elif tid=='C04':
                value=actual['final_oxide']
                lines+=['',f'最终交付：cladOuter 氧化层厚度 {value["mean_m"]:.12g} m，即 {value["mean_um"]:.9f} μm；时间单位为天，最终目录 `{actual["final_time_directory"]}`。']
            else:
                lines+=['','本题源baseCase多数物理模块为fromLatestTime，气体/FGR未开启；这一轨迹说明源配置下的运行和状态交接，不把它解释为完整活跃燃料演化模型验证。']
            lines+=['','## 关键动作速查','','下列入口指向技能加载、运行/重跑、明确的工具异常、Python异常或超过30秒的调用；完整动作在后文逐轮列出。','','| 轮次 | 动作 | 中文说明 |','|---|---|---|']
            for call in calls:
                duration=(call['ended_ms']-call['started_ms'])/1000
                desc=call['args'].get('description','')
                if call['tool']=='skill' or call.get('tool_error') or duration>=30 or any('异常回溯' in x for x in diagnostics(call)) or re.match(r'(?:Run |Re-run |Rerun |Repair restart|Create clean second|Create independent continuation)',desc):
                    action=translated_action(call,translations,todos,workspace,root).replace('|','\\|')
                    lines.append(f'| {call["step"]} | [{call["number"]:03d}](#action-{call["number"]:03d}) | {action} |')
            lines+=['','## 逐轮工具轨迹','']
            for step,stamp in steps.items():
                batch=by_step.get(step,[])
                lines += [f'### 第 {step} 轮 · {local_time(stamp)}','']
                if not batch:
                    lines+=['本轮未提交工具调用；保留轮次编号，不补写不存在的动作。',''];continue
                lines += [f'本轮提交 {len(batch)} 次工具调用。'+('多项调用属于同一模型轮次，不据此推断宿主并行执行。' if len(batch)>1 else ''),'']
                for call in batch:
                    n=call['number'];action=translated_action(call,translations,todos,workspace,root);summary,notes=return_summary(call)
                    elapsed=(call['ended_ms']-call['started_ms'])/1000
                    param,structured=params_view(call,todos,workspace,root)
                    lines += [f'<a id="action-{n:03d}"></a>',f'**动作 {n:03d}：{action}**','',f'- 工具：{TOOLS[call["tool"]]}（`{call["tool"]}`）；发起于 {local_time(call["started_ms"])}；记录间隔 {elapsed:.3f} 秒。',f'- 返回摘要：{summary}']
                    for note in notes:lines.append('- '+note)
                    excerpts=key_output(call)
                    for fragment in excerpts:lines.append('- '+fragment)
                    if call['tool']=='bash' and 'Analytical' in call['args']['description']:
                        lines.append('- 此处解析预测由受测模型自行增加；题面不要求参考解对照，本轮外部验收没有用它评分。')
                    lines+=['','<details>','<summary>展开参数或命令原文，以及原始记录位置</summary>','',param,'',f'[原始调用]({trace}:{call["call_line"]})；[原始返回]({trace}:{call["result_line"]})。调用事件序号 {call["call_seq"]}，返回事件序号 {call["result_seq"]}。','','</details>','']
                    dataset.append({'任务':tid,'组别':group,'动作序号':n,'模型轮次':step,'发起时间_北京时间':local_time(call['started_ms']),'记录间隔秒':round(elapsed,3),'工具':call['tool'],'中文动作':action,'参数':structured,'中文返回摘要':summary,'关键输出片段':excerpts,'中文诊断':notes,'原始定位':{'文件':str(trace.relative_to(root)),'调用行':call['call_line'],'返回行':call['result_line'],'调用事件序号':call['call_seq'],'返回事件序号':call['result_seq'],'调用ID':call['id']}})
            lines+=['## 原生文件操作索引','','此表只统计 read、write、edit 工具；bash 命令中的读取和修改仍完整保留在逐轮轨迹中，不把文件名引用误当作真实文件访问次数。','','| 文件 | 读取 | 写入 | 修改 | 对应动作 |','|---|---:|---:|---:|---|']
            for file,operations in native_files.items():
                counts=Counter(tool for _,tool in operations);links='、'.join(f'[{n:03d}](#action-{n:03d})' for n,_ in operations)
                lines.append(f'| `{short_path(file,workspace,root)}` | {counts["read"]} | {counts["write"]} | {counts["edit"]} | {links} |')
            lines+=['','[返回六次运行总索引](总索引.md)。']
            path.write_text('\n'.join(lines)+'\n')
            manifest['文档'].append({'任务':tid,'组别':group,'文件':name,'模型轮次':len(steps),'工具调用数':len(calls),'返回记录数':sum(c['result_line'] is not None for c in calls),'原生文件操作数':sum(c['tool'] in ['read','write','edit'] for c in calls),'SHA256':sha(path)})
            index.append(f'| {tid} {TASK_NAMES[tid]} | {group} | {run["wall_seconds"]:.3f} | {len(steps)} | {len(calls)} | {actual["solver_starts"]} | [打开]({name}) |')
    assert len(dataset)==715
    assert all(sha(root/path)==value for path,value in manifest['源文件SHA256'].items())
    with (destination/'工具调用中文记录.jsonl').open('w') as stream:
        for row in dataset:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    index+=['','使用说明：每个“第几轮”对应一次原始模型步骤；动作序号在各文件内从001开始。同轮多工具按调用事件的时间排列。各文件保留无工具轮次，避免将只生成消息的一轮误算为工具执行。','','变量与工具：T为温度，D为位移；DiamCold为冷态直径，GapCold按模型定义为冷态直径间隙。blockMesh生成网格，checkMesh检查网格，changeDictionary修改字典与边界设置，foamDictionary读取或修改OpenFOAM字典。查询求解器帮助、准备输入、生成网格和纯提取不计真实OFFBEAT启动。','','[机器可读中文工具记录](工具调用中文记录.jsonl)包含全部715条动作及原始行号；[翻译清单](翻译清单.json)记录各文件数量和原始轨迹校验和。原始轨迹和已有结果均未修改，本次没有再次启动DSH或求解器。','','简要比较仍见[结果汇总](../结果汇总.md)，性能和工作流问题见[执行观察](../执行观察.md)。']
    (destination/'总索引.md').write_text('\n'.join(index)+'\n')
    manifest['总工具调用数']=len(dataset);manifest['原始轨迹保持不变']=True
    save(destination/'翻译清单.json',manifest)
    print(json.dumps({'documents':len(manifest['文档']),'tool_calls':len(dataset),'translated_unique_descriptions':len(translations),'destination':str(destination)},ensure_ascii=False))


if __name__=='__main__': main()
