"""离线查询维护过的软件事实，并对输入做有限、可解释的已知问题检查。"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shlex
import subprocess

from .foam_edit import FoamEditError, get_foam_entry
from .geometry_angle import TransformError, validated_case_file

ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT/'skills/prepare-offbeat-case/references/software-capabilities/catalog.json'
ALIASES={'mechanics':'mechanicsSolver','thermal':'thermalSolver','gas':'gapGas','transport':'elementTransport','power':'heatSource','time':'controls','units':'fields','models':'selectors','properties':'property_models','tools':'public_apis','dependencies':'rules'}


def load_catalog():
    return json.loads(CATALOG.read_text())


def query(keys, *, full=False):
    """一次返回多个选择器/主题/操作；只读静态表，不探测安装或访问网络。"""
    catalog=load_catalog();out={}
    for original in keys:
        key=ALIASES.get(original,original)
        if key in catalog['selectors']:
            value=catalog['selectors'][key]
            if not full:
                value={k:v for k,v in value.items() if k!='sources'}
                value['choices']=[{k:x[k] for k in ('value','level','meaning')} for x in value['choices']]
            out[original]=value
        elif key in ('selectors','materials','property_models','boundaries','fields','controls','parameters','operations','rules','public_apis','tooling','limitations'):
            out[original]=catalog[key]
        else:
            match=next((x for x in catalog['operations'] if x['id']==key),None)
            if match is None:raise ValueError(f'能力项未收录：{original}；可用summary查询索引，未知不等于软件不支持')
            out[original]=match
    return {'catalog_id':catalog['catalog_id'],'profile':catalog['profile']['name'],'scope':catalog['scope'],'items':out}


def _keys(case, file, entry=None):
    path=validated_case_file(case,file)
    command=['foamDictionary',str(path),'-disableFunctionEntries','-no-libs','-noFunctionObjects']
    if entry:command+=['-entry',entry]
    command+=['-keywords']
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    if result.returncode:raise FoamEditError(result.stderr.strip()[:1400])
    return shlex.split(result.stdout)


def _scalar(text):
    return text.strip().rstrip(';').strip().strip('"') if text is not None else None


def _numbers(text):
    if text is None:return None
    tokens=text.replace('(',' ').replace(')',' ').replace(';',' ').split()
    try:values=[float(x) for x in tokens]
    except ValueError:return None
    return values if values and all(math.isfinite(x) for x in values) else None


def check_case(case, *, source=None):
    """检查当前配置档已知问题；不会改卡/启动OFFBEAT，不是完整物理认证。

    主要面向新鲜初态0；续算或包含片段的未展开部分明确报告未检查。
    已知非法选择器和被激活的fuelRodGap/none组合为errors，未知值和风险为warnings。
    """
    case=Path(case).resolve();source=Path(source).resolve() if source is not None else None
    catalog=load_catalog();errors=[];warnings=[];observed={};reads={}
    def issue(items,code,message,**details):items.append({'code':code,'message':message,**details})
    def read(root,file,entry,optional=False):
        key=(str(root),file,entry)
        if key not in reads:
            try:reads[key]=get_foam_entry(root,file,entry)
            except (FoamEditError,TransformError,ValueError,OSError):
                if not optional:raise
                reads[key]=None
        return reads[key]
    try:
        keys=_keys(case,'constant/solverDict')
        for key,data in catalog['selectors'].items():
            if key not in keys:continue
            value=_scalar(read(case,'constant/solverDict',key));observed[key]=value
            if value in data.get('known_invalid',{}):
                issue(errors,'unsupported_selector',data['known_invalid'][value],entry=key,value=value,suggested=data.get('preferred_inactive'))
            elif value not in {x['value'] for x in data['choices']}:
                issue(warnings,'unverified_selector','本表未核实该值；保留用户/源的定义，按一般流程和运行反馈确认，不因未收录拒绝任务。',entry=key,value=value)
        boundaries={}
        if (case/'0/T').is_file():
            try:
                for patch in _keys(case,'0/T','boundaryField'):
                    kind=_scalar(read(case,'0/T','boundaryField/'+patch+'/type',optional=True))
                    if kind:boundaries[patch]=kind
            except FoamEditError as e:issue(warnings,'boundary_not_checked',str(e)[:500])
        else:issue(warnings,'initial_boundary_not_checked','未发现0/T；当前检查不推断重启时刻或生成器产物，相关边界未检查。')
        observed['temperature_boundaries']=boundaries
        gas=observed.get('gapGas');thermal=observed.get('thermalSolver')
        consumers=[p for p,v in boundaries.items() if v=='fuelRodGap']
        if thermal=='solidConduction' and consumers:
            if gas=='none':issue(errors,'gas_conductivity_required','当前热求解会评价fuelRodGap，而none气体模型不提供所需气体导热物性；恢复适用源模型或明确改变热边界物理。',patches=consumers,entry='gapGas')
            elif gas not in ('FRAPCON','TRISO'):issue(warnings,'gas_capability_unverified','需要确认所选气体模型为fuelRodGap提供导热物性；本表未验证该组合。',value=gas,patches=consumers)
        control=case/'system/controlDict'
        if control.is_file():
            end=_numbers(read(case,'system/controlDict','endTime',optional=True))
            model=observed.get('heatSource')
            if model in ('timeDependentLhgr','timeDependentVhgr'):
                points=_numbers(read(case,'constant/solverDict','heatSourceOptions/timePoints',optional=True))
                values=_numbers(read(case,'constant/solverDict','heatSourceOptions/'+('lhgr' if model=='timeDependentLhgr' else 'vhgr'),optional=True))
                if points and values and len(points)!=len(values):issue(errors,'load_table_length','字面时间节点与载荷值数量不一致，应按该模型配对。')
                if end and points:
                    if max(points)<=end[-1]:issue(warnings,'load_endpoint_risk','载荷末点未晚于终点；本机已观察到查下一标记越界。保留已有较晚末点，确认具体模型处理；不要为此重算已完成结果。',endTime=end[-1],last_time=max(points))
                    if points!=sorted(points) or len(set(points))!=len(points):issue(warnings,'load_time_order','时间节点不严格递增；核对对应模型要求。')
                if source is not None and points and values and end:
                    old_model=_scalar(read(source,'constant/solverDict','heatSource',optional=True))
                    old_p=_numbers(read(source,'constant/solverDict','heatSourceOptions/timePoints',optional=True))
                    old_v=_numbers(read(source,'constant/solverDict','heatSourceOptions/'+('lhgr' if model=='timeDependentLhgr' else 'vhgr'),optional=True))
                    su=_scalar(read(source,'system/controlDict','userTime/type',optional=True)) or 'seconds'
                    tu=_scalar(read(case,'system/controlDict','userTime/type',optional=True)) or 'seconds'
                    factors={'seconds':1.,'hours':3600.,'days':86400.}
                    covered=old_p and su in factors and tu in factors and min(old_p)*factors[su]<=0 and max(old_p)*factors[su]>end[-1]*factors[tu]
                    if old_model==model and covered and old_v and all(math.isclose(x,values[0],rel_tol=1e-12) for x in old_v+values) and points!=old_p:
                        issue(warnings,'source_load_already_sufficient','源的恒定载荷和时间覆盖已经满足该区间。核对本次重写节点的必要性；用户未要求改时间网格时优先沿用源。')
            functions=read(case,'system/controlDict','functions',optional=True)
            if functions:
                if re.search(r'\btype\s+lineUniform\s*;',functions):issue(warnings,'legacy_sample_type','本机v2506曾拒绝lineUniform；采样启用时需使用受支持语法（已见uniform）或合适的已有场提取。')
                if 'patchProbes' in functions and 'patchName' in functions:issue(warnings,'legacy_patch_probes','源中patchProbes/patchName组合需要核对；本机曾要求patch。若函数被禁用或已有其他有效配置，勿盲目改写。')
        else:issue(warnings,'control_not_checked','未发现controlDict，时间覆盖和采样未检查。')
        if source is not None:
            for key in ('gapGas','heatSource','materialProperties','rheology'):
                if key not in observed:continue
                old=_scalar(read(source,'constant/solverDict',key,optional=True))
                if old is not None and old!=observed[key]:issue(warnings,'source_model_changed','模型选择器发生变化；确认来自用户要求或必要依赖，不为纯热学/整理输入一并关闭无关模型。',entry=key,source=old,target=observed[key])
    except (FoamEditError,TransformError,OSError,ValueError,subprocess.TimeoutExpired) as e:
        issue(warnings,'check_incomplete','部分字面输入无法通过已准备的原生接口读取；不扩展宏或执行代码，不把未检查当通过。',detail=str(e)[:1000])
        observed['incomplete']=True
    status='known_errors' if errors else 'partially_checked' if observed.get('incomplete') else 'no_known_errors'
    return {'status':status,'errors':errors,'warnings':warnings,'observed':observed,'native_entry_reads':len(reads),
            'profile':catalog['profile']['name'],'profile_basis':'当前能力配置档；安装身份由维护/启动阶段确认，检查器不重复探测二进制或源码。',
            'scope':'仅当前配置档的已知字面输入与直接依赖，初始边界按0/T；不证明包含文件、重启状态、全部模型参数或物理精度。','solver_starts':0,'input_files_modified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['summary','show','check']);p.add_argument('keys',nargs='*')
    p.add_argument('--case',type=Path);p.add_argument('--source',type=Path);p.add_argument('--full',action='store_true')
    args=p.parse_args()
    if args.action=='summary':
        c=load_catalog();result={'profile':c['profile'],'levels':c['levels'],'coverage':c['coverage'],'topics':list(ALIASES),'selectors':list(c['selectors']),'operations':[x['id'] for x in c['operations']]}
    elif args.action=='show':
        if not args.keys:p.error('show 后提供一个或多个选择器/主题/操作ID')
        result=query(args.keys,full=args.full)
    else:
        if args.case is None:p.error('check 要求 --case')
        result=check_case(args.case,source=args.source)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 2 if result.get('errors') else 0

if __name__=='__main__':raise SystemExit(main())
