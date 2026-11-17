"""Validated multi-solve summaries. No solver or optimization is run here."""
from __future__ import annotations
import copy
import math
import re

STATUSES={'queued','running','completed','failed','skipped'}
KINDS={'scan','optimization','uncertainty'}
CHARTS={'response','scatter','history','histogram','cdf'}

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',value):raise ValueError('研究标识无效')
    return value

def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def text(value,limit=120):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('研究文本无效')
    return value

def validate_study(value,view_ids=()):
    if not isinstance(value,dict) or value.get('schema')!='mandifuel.study/v1' or value.get('kind') not in KINDS:raise ValueError('研究格式或类型不受支持')
    study={'schema':value['schema'],'kind':value['kind'],'label':text(value.get('label',''))}
    def preview(raw):
        if not isinstance(raw,dict) or set(raw)-{'fields','time'}:raise ValueError('预览配置无效')
        fields=raw.get('fields',[])
        if not isinstance(fields,list) or not 1<=len(fields)<=16 or any(not isinstance(f,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?',f) for f in fields):raise ValueError('预览字段无效')
        when=raw.get('time','latest')
        if not isinstance(when,str) or len(when)>300:raise ValueError('预览时间无效')
        if when not in {'latest','all'}:
            try:
                if not all(math.isfinite(float(t)) and float(t)>0 for t in when.split(',')):raise ValueError()
            except ValueError:raise ValueError('预览时间无效')
        return {'fields':list(fields),'time':when}
    if 'preview' in value:study['preview']=preview(value['preview'])
    definitions={}
    for key in ('parameters','responses'):
        raw=value.get(key,[])
        if not isinstance(raw,list) or not raw or len(raw)>80:raise ValueError('研究变量列表无效')
        rows=[];seen=set()
        for item in raw:
            ident=identifier(item['id'])
            if ident in seen or ident in definitions:raise ValueError('研究变量标识重复')
            seen.add(ident);row={'id':ident,'label':text(item.get('label',ident)),'unit':text(item.get('unit',''),60),'type':item.get('type','number')}
            if row['type'] not in {'number','category'} or key=='responses' and row['type']!='number':raise ValueError('研究变量类型无效')
            if 'goal' in item:
                if key!='responses' or item['goal'] not in {'min','max'}:raise ValueError('目标方向无效')
                row['goal']=item['goal']
            if 'bounds' in item:
                bounds=item['bounds']
                if key!='responses' or not isinstance(bounds,dict) or not bounds or set(bounds)-{'min','max'} or any(not number(v) for v in bounds.values()):raise ValueError('响应约束无效')
                if 'min' in bounds and 'max' in bounds and bounds['min']>bounds['max']:raise ValueError('响应约束上下界无效')
                row['bounds']=dict(bounds)
            definitions[ident]=row;rows.append(row)
        study[key]=rows
    raw=value.get('runs',[])
    if not isinstance(raw,list) or len(raw)>10000:raise ValueError('参数组数量无效，单份交付最多10000组')
    runs=[];seen=set();owners={};views=set(view_ids)
    for index,item in enumerate(raw):
        ident=identifier(item['id'])
        if ident in seen:raise ValueError('参数组标识重复')
        seen.add(ident);status=item.get('status','queued')
        if status not in STATUSES:raise ValueError('参数组状态无效')
        row={'id':ident,'label':text(item.get('label','')),'status':status,'parameters':{},'responses':{},'viewIds':[]}
        for key in ('parameters','responses'):
            values=item.get(key,{})
            if not isinstance(values,dict) or set(values)-{d['id'] for d in study[key]}:raise ValueError('参数组含未定义变量')
            for name,v in values.items():
                if v is None:continue
                if definitions[name]['type']=='number':
                    if not number(v):raise ValueError('研究数值必须有限，缺失值请省略')
                else:text(v)
                row[key][name]=v
        # Failed/pending solves never acquire chart values or a pretend result view.
        if status in {'failed','skipped'} and (row['responses'] or item.get('viewIds')) or status=='queued' and row['responses']:raise ValueError('失败或未执行组不能登记响应值和模型结果')
        refs=item.get('viewIds',[])
        if not isinstance(refs,list) or len(set(refs))!=len(refs) or any(v not in views for v in refs):raise ValueError('参数组引用了未登记或重复的模型视图')
        for ref in refs:
            if ref in owners:raise ValueError('模型视图必须唯一绑定参数组')
            owners[ref]=ident
        row['viewIds']=list(refs)
        if 'defaultView' in item:
            if item['defaultView'] not in refs:raise ValueError('参数组默认模型无效')
            row['defaultView']=item['defaultView']
        if 'caseRoot' in item:row['caseRoot']=text(item['caseRoot'],2000)
        if 'preview' in item:row['preview']=preview(item['preview'])
        if 'iteration' in item:
            if not number(item['iteration']) or item['iteration']<0:raise ValueError('迭代序号无效')
            row['iteration']=item['iteration']
        if 'error' in item:row['error']=text(item['error'],800)
        runs.append(row)
    study['runs']=runs
    if 'defaultRun' in value:
        if value['defaultRun'] not in seen:raise ValueError('默认参数组不存在')
        study['defaultRun']=value['defaultRun']
    charts=value.get('charts',[])
    if not isinstance(charts,list) or len(charts)>20:raise ValueError('图表配置无效')
    study['charts']=[];chart_ids=set()
    for item in charts:
        ident=identifier(item['id']);kind=item.get('type')
        if ident in chart_ids or kind not in CHARTS:raise ValueError('图表类型或标识无效')
        chart_ids.add(ident);row={'id':ident,'type':kind,'label':text(item.get('label',ident))}
        if item.get('y') not in {d['id'] for d in study['responses']}:raise ValueError('图表响应不存在')
        row['y']=item['y']
        if kind in {'response','scatter'}:
            if item.get('x') not in definitions:raise ValueError('图表横坐标不存在')
            row['x']=item['x']
        study['charts'].append(row)
    if 'defaultChart' in value:
        if value['defaultChart'] not in chart_ids:raise ValueError('默认图表不存在')
        study['defaultChart']=value['defaultChart']
    return study

def summary(study,version=0):
    counts={s:0 for s in STATUSES}
    for row in study['runs']:counts[row['status']]+=1
    return {'kind':study['kind'],'label':study['label'],'total':len(study['runs']),'counts':counts,'version':version}
