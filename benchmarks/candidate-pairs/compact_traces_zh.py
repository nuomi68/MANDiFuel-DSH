#!/usr/bin/env python3
"""Render the Chinese observable trajectory as one line per tool event."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlparse


def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def short_path(value):
    p=str(value).replace('`','')
    if '/workspace/' in p:p=p.split('/workspace/',1)[1]
    if 'frozen-plugin/' in p:p='插件/'+p.split('frozen-plugin/',1)[1]
    p=p.replace('实验目录/','')
    if p.startswith('插件/') and '/scripts/' in p:return '插件/'+p.split('/scripts/',1)[1]
    if p.startswith('插件/') and '/references/' in p:return '插件/参考/'+p.rsplit('/',1)[1]
    if p.startswith('/home/lwz/offbeat/'):return '源码/'+p.rsplit('/',1)[1]
    return p


def action_text(row):
    text=row['中文动作']
    text=re.sub(r'`([^`]+)`',lambda m:short_path(m[1]),text)
    tool=row['工具'];a=row['参数']
    if tool=='web_search':
        query=' '.join(a.get('查询原文',[]))
        if 'prepare-offbeat-case' in query:text='搜索网页：技能名 prepare-offbeat-case'
        elif 'GapCold' in query:text='搜索网页：GapCold 定义'
        elif 'fromLatestTime' in query:text='搜索网页：fromLatestTime 与续算'
        else:text='搜索网页：OFFBEAT 相关资料'
    if tool=='web_fetch':
        url=unquote(a.get('网页地址',''));parsed=urlparse(url)
        file=parsed.path.split('/repository/files/',1)[-1].removesuffix('/raw')
        if re.search(r'\.(?:C|H|cpp|hpp)$',file):text='读取远程源码：'+file.rsplit('/',1)[-1]
        elif '/repository/tree' in url:
            path=parse_qs(parsed.query).get('path',['仓库根目录'])[0];text='列出远程仓库目录：'+path
        elif '/repository/files/' in url:text='读取远程文件：'+file.rsplit('/',1)[-1]
        else:text='读取网页：'+(parsed.path.rstrip('/').rsplit('/',1)[-1] or parsed.netloc)
    if tool=='todo_write':
        entries=a.get('待办',[]);counts=Counter(x['状态'] for x in entries)
        text=f'更新待办：待执行{counts["待执行"]}/进行中{counts["进行中"]}/已完成{counts["已完成"]}'
    if tool=='edit':
        new=a.get('新片段','');file=a.get('文件路径','')
        if file.endswith('rodDict') and 'rOuterFuel' in new:text+='（同步燃料及包壳半径）'
        elif file.endswith('solverDict') and ('DiamCold' in new or 'GapCold' in new):text+='（同步冷态尺寸）'
        elif 'foamDictionary' in new and 'boundary' in new:text+='（边界值改用原生字典读取）'
        elif 'import subprocess' in new and 'import subprocess' not in a.get('原片段',''):text+='（增加 subprocess 导入）'
    return ' '.join(text.split())


def result_text(row):
    notes=row['中文诊断'];all_notes=' '.join(notes);summary=row['中文返回摘要'];parts=[]
    if '工具前台命令超时' in all_notes:parts.append('前台命令超时并被终止')
    elif '工具命令被信号终止' in all_notes:parts.append('命令被信号终止')
    elif '编辑工具要求先读取' in all_notes:parts.append('编辑被拒：须先读取')
    elif '文件自上次读取后已变化' in all_notes:parts.append('写改被拒：文件已变化，须重读')
    elif '网页读取失败' in all_notes:parts.append('网页请求失败')
    elif '异常回溯' in all_notes:
        if '双向对应元数据' in all_notes:parts.append('脚本报错：fuelOuter 双向元数据不完整')
        elif '未发现数值时间目录' in all_notes:parts.append('脚本报错：未找到数值时间目录')
        elif '缺少字典键' in all_notes:
            m=re.search(r'缺少字典键：`([^`]+)`',all_notes);parts.append('脚本报错：缺少键 '+(m[1] if m else ''))
        elif '模块不存在' in all_notes:parts.append('脚本报错：模块不存在')
        elif '文件不存在' in all_notes:parts.append('脚本报错：文件不存在')
        elif '访问被拒绝' in all_notes:parts.append('脚本报错：访问受限')
        else:parts.append('脚本异常')
        if '退出码为 0' in summary:parts.append('管道仍返回0')
    else:
        if '致命读取错误' in all_notes:parts.append('日志含续算压力表EOF错误')
        elif '致命错误文本' in all_notes:parts.append('输出含FOAM错误文本')
        if '访问被拒绝路径' in all_notes or '读取权限拒绝' in all_notes:parts.append('访问受限')
        elif '路径不存在' in all_notes:parts.append('路径不存在')
        if '工具明确报告异常' in summary and not parts:parts.append('工具报错')
        codes=re.search(r'退出码为 ([\d, -]+)',summary)
        nonzero=[int(x) for x in codes[1].split(',') if x.strip() and int(x)!=0] if codes else []
        if nonzero and not parts:
            if 'diff' in all_notes:parts.append('退出'+str(nonzero[0])+'（含diff）')
            elif 'grep' in all_notes:parts.append('退出'+str(nonzero[0])+'（含grep）')
            else:parts.append('退出'+str(nonzero[0]))
        if '后台作业仍在运行' in all_notes:parts.append('作业运行中')
        elif row['工具']=='job_output' and '后台作业已结束' in all_notes and not parts:parts.append('作业结束')
    duration=row['记录间隔秒']
    runtime=re.search(r'shell 计时为 (\d+) 分 ([\d.]+) 秒',summary)
    jobtime=int(runtime[1])*60+float(runtime[2]) if runtime else None
    if duration>=1:parts.append(f'调用{duration:.1f}s')
    if jobtime is not None and jobtime>=10 and (duration<1 or abs(duration-jobtime)>2):parts.append(f'作业{jobtime:.1f}s')
    return '；'.join(parts)


def event_line(row):
    clock=row['发起时间_北京时间'].split(' ')[1].split('.')[0]
    action=action_text(row);result=result_text(row)
    return f'{row["动作序号"]:03d}  {clock}  R{row["模型轮次"]:03d}  {action}'+(' → '+result if result else '')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);args=parser.parse_args();root=args.run_root.resolve();folder=root/'中文详细轨迹';expanded=folder/'展开版';expanded.mkdir(exist_ok=True)
    rows=[json.loads(line) for line in (folder/'工具调用中文记录.jsonl').read_text().splitlines()]
    manifest=load(folder/'翻译清单.json');comparison=load(root/'comparison.json');verified=load(root/'verification.json')
    combined=['# 六次运行 一行事件汇总','','每行一个工具调用及其结果；北京时间。R为模型轮次；只在异常、重试或明显耗时时追加结果说明。共715行事件。','']
    index=['# 六次运行的中文轨迹','','[合并查看六次运行的一行轨迹](六次运行_一行事件汇总.md)','','每行一个工具调用及其结果，保留时间、轮次、文件名、错误和重跑；共715条。R表示模型轮次，同轮可有多个事件。无异常时省略“已返回”等重复文字。工具调用不等于一次OFFBEAT启动。时间均为北京时间。','','| 任务 | 裸DSH | Skill |','|---|---|---|']
    export_manifest={'格式':'每行一个工具调用及其结果','事件总数':len(rows),'文档':[],'源中文记录SHA256':sha(folder/'工具调用中文记录.jsonl'),'原始轨迹哈希保持不变':all(sha(root/p)==h for p,h in manifest['源文件SHA256'].items())}
    for tid in ['P02','C04','W01']:
        link=[]
        for group,arm in [('裸DSH','bare'),('Skill','skill')]:
            name=f'{tid}_{group}_逐步中文轨迹.md';path=folder/name;backup=expanded/name
            # Keep the existing expanded documents once, then replace the same
            # user-facing filenames with the compact representation.
            if not backup.exists():
                backup.write_text(path.read_text().replace('](总索引.md)','](../总索引.md)'))
            selected=[r for r in rows if r['任务']==tid and r['组别']==group]
            stats=comparison['tasks'][tid][arm];actual=verified['tasks'][tid][arm]
            event_lines=[event_line(r) for r in selected]
            assert len(event_lines)==stats['tool_calls'] and all('\n' not in x for x in event_lines)
            intro=f'{stats["wall_seconds"]:.1f}秒｜{len(selected)}条工具事件｜{stats["steps"]}轮｜OFFBEAT启动{actual["solver_starts"]}次'
            document=[f'# {tid} {group} 一行轨迹','',intro+f'｜[展开详情](展开版/{name})','', '```text',*event_lines,'```','']
            path.write_text('\n'.join(document))
            combined += [f'## {tid} {group}', '',intro,'','```text',*event_lines,'```','']
            export_manifest['文档'].append({'任务':tid,'组别':group,'文件':name,'事件数':len(selected),'SHA256':sha(path),'详情文件':'展开版/'+name})
            for item in manifest['文档']:
                if item['任务']==tid and item['组别']==group:item.update(文件='展开版/'+name,SHA256=sha(backup))
            link.append(f'[{len(selected)}行]({name})')
        index.append(f'| {tid} | {link[0]} | {link[1]} |')
    index += ['', '原有展开内容保存在[展开版](展开版/)，完整命令、返回摘要和源日志定位可按需查看。']
    (folder/'总索引.md').write_text('\n'.join(index)+'\n')
    (folder/'六次运行_一行事件汇总.md').write_text('\n'.join(combined))
    manifest['压缩版索引']='总索引.md';manifest['压缩版生成脚本']=str(Path(__file__).resolve());save(folder/'翻译清单.json',manifest)
    assert export_manifest['原始轨迹哈希保持不变'] and len(rows)==715
    save(folder/'单行版清单.json',export_manifest)
    print(json.dumps({'documents':len(export_manifest['文档']),'events':len(rows),'source_unchanged':export_manifest['原始轨迹哈希保持不变'],'combined':str(folder/'六次运行_一行事件汇总.md')},ensure_ascii=False))


if __name__=='__main__':main()
