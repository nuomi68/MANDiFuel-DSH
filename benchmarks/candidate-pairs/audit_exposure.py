#!/usr/bin/env python3
"""Audit observable tool calls/results for cross-arm and organizer exposure."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import re


def texts(blocks):
    out=[]
    for b in blocks if isinstance(blocks,list) else []:
        if not isinstance(b,dict): continue
        if b.get('type')=='text': out.append(b.get('text',''))
        elif b.get('type')=='tool-result': out.extend(texts(b.get('content',[])))
    return out


def audit(root):
    manifest=json.loads((root/'manifest.json').read_text()); report={'checked_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'scope':'工具参数和返回内容；不导出模型推理正文','arms':{}}
    for task in manifest['tasks']:
        task_id=task['id']
        for arm in manifest.get('arms',['bare','skill']):
            folder=root/task_id/arm; calls={}; results={}
            for f in (folder/'traces').rglob('session.jsonl'):
                for line in f.open():
                    e=json.loads(line); d=e.get('data',{})
                    if e.get('type')=='tool/call':
                        a=d.get('arguments',{})
                        if isinstance(a,str):
                            try: a=json.loads(a)
                            except ValueError: a={}
                        calls[d['callId']]={'step':d.get('step'),'name':d.get('name'),'args':a}
                    elif e.get('type')=='tool/result':
                        message=d.get('message',{}); call_id=message.get('source',{}).get('callId')
                        results[call_id]='\n'.join(texts(message.get('content',[])))
            hits=[]
            for call_id,c in calls.items():
                a=c['args']; command=str(a.get('command',''))+' '+str(a.get('file_path',''))
                output=results.get(call_id,''); kinds=[]
                if re.search(r'2026-11-12-candidate-bank|candidates\.json|execution-manifest\.json|source-evidence\.json|evaluation-policy\.json',command): kinds.append('organizer_reference')
                if arm=='bare' and re.search(r'frozen-plugin|SKILL\.md|mandifuel_run|mandifuel_prepare|MANDIFUEL_PLUGIN_ROOT|skills/',command): kinds.append('bare_plugin_reference')
                other='skill' if arm=='bare' else 'bare'
                if re.search(r'/(P02|C04|W01)/'+other+r'/',command): kinds.append('cross_arm_reference')
                if str(task['source']) in command and 'Allrun' in command: kinds.append('original_case_recipe_reference')
                if not kinds: continue
                hints=bool(re.search(r'"(?:oracle|expected_workflow|skill_value_hypothesis|pitfalls)"\s*:',output))
                skill_body=bool(re.search(r'name:\s*(?:prepare|execute|extract|conduct|orchestrate)-offbeat-',output))
                hits.append({'call_id':call_id,'step':c['step'],'tool':c['name'],'description':a.get('description'),'kinds':kinds,'read_denial_in_return':bool(re.search(r'Permission denied|EACCES|permission denied',output)),'organizer_hints_in_return':hints,'skill_document_body_in_return':skill_body,'tool_result_sha256':hashlib.sha256(output.encode()).hexdigest()})
            preflight=folder/'preflight.json'
            isolation=json.loads(preflight.read_text()) if preflight.exists() else None
            report['arms'][task_id+'/'+arm]={'references':hits,'organizer_hint_reads_observed':sum(h['organizer_hints_in_return'] for h in hits),'bare_skill_document_reads_observed':sum(h['skill_document_body_in_return'] for h in hits) if arm=='bare' else 0,'isolation_preflight_passed':bool(isolation and isolation['exit_code']==0 and isolation.get('isolation',{}).get('passed'))}
    report['all_arm_isolation_preflights_passed']=all(a['isolation_preflight_passed'] for a in report['arms'].values())
    report['organizer_or_bare_skill_exposure_observed']=any(a['organizer_hint_reads_observed'] or a['bare_skill_document_reads_observed'] for a in report['arms'].values())
    report['interpretation']='受污染预跑，不用于裸DSH与skill正式收益结论' if report['organizer_or_bare_skill_exposure_observed'] else '未在直接引用的返回中发现题库提示或裸组技能正文；读取隔离另以启动前内核检查为据'
    (root/'exposure-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(); p.add_argument('run_root',type=Path); args=p.parse_args(); r=audit(args.run_root.resolve())
    print(json.dumps({k:r[k] for k in ['all_arm_isolation_preflights_passed','organizer_or_bare_skill_exposure_observed','interpretation']},ensure_ascii=False))


if __name__=='__main__': main()
