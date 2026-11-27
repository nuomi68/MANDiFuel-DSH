"""Validate an agent-authored application contract against the physical adapter."""
import re
from .thermal_rod import PARAMETERS

def label(value):
    if not isinstance(value,str) or not 0<len(value.strip())<=100:
        raise ValueError('名称需要 1–100 个字符')
    return value.strip()

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,47}',value):
        raise ValueError('无效的契约标识')
    return value

def views(items,outputs,params):
    if not isinstance(items,list) or len(items)>16:
        raise ValueError('组件清单应为至多 16 项的数组')
    by_id={o['id']:o for o in outputs}
    result=[]
    for item in items:
        if not isinstance(item,dict) or set(item)-{'id','type','title','output','slot','scope','x','y'}:
            raise ValueError('组件只能引用已注册显示属性')
        output=by_id.get(identifier(item.get('output')))
        if not output or output['kind']=='field':
            raise ValueError('图表和表格需要一个已定义的数据输出')
        kind=item.get('type')
        if kind not in ('lineChart','scatterChart','barChart','table'):
            raise ValueError('未知的显示组件')
        node=dict(id=identifier(item.get('id')),title=label(item.get('title')),type=kind,output=output['id'],
                  slot=item.get('slot','main'),scope=item.get('scope','selected'))
        if node['slot'] not in ('main','aside') or node['scope'] not in ('selected','history'):
            raise ValueError('无效的组件位置或工况范围')
        cols={'case','value',*(p['id'] for p in params)}
        if output['kind']=='profile':cols.add('radius')
        if output['kind']=='heatFlow':cols.add('quantity')
        if kind!='table':
            node.update(x=item.get('x',{'profile':'radius','heatFlow':'quantity'}.get(output['kind'],'case')),y=item.get('y','value'))
            if identifier(node['x']) not in cols or identifier(node['y']) not in cols-{'case','quantity'}:
                raise ValueError('图表轴没有对应的契约数据列')
        result.append(node)
    if len({n['id'] for n in result})!=len(result):
        raise ValueError('组件标识重复')
    return result

def validate(proposal,defaults,*,heat_flow=False):
    if not isinstance(proposal,dict) or set(proposal)-{'title','parameters','outputs','components'}:
        raise ValueError('需提交含 title、parameters、outputs 的应用定义')
    result={'title':label(proposal.get('title'))}
    for key in ('parameters','outputs'):
        items=proposal.get(key)
        if not isinstance(items,list) or not 1<=len(items)<=24:
            raise ValueError(f'{key} 需要 1–24 项')
        checked=[]
        for item in items:
            if not isinstance(item,dict):raise ValueError('参数或输出需要一个对象')
            row=dict(id=identifier(item.get('id')),label=label(item.get('label')))
            if key=='parameters':
                binding=identifier(item.get('binding'))
                if set(item)-{'id','label','binding'} or binding not in PARAMETERS or row['id'] in {'case','value','radius','runId','region'}:
                    raise ValueError('参数需要已注册的物理绑定及独立标识')
                row.update(binding=binding,bindings=PARAMETERS[binding][2],unit=PARAMETERS[binding][1],default=defaults[binding])
            else:
                kind=item.get('kind')
                if kind=='heatFlow':
                    if not heat_flow or set(item)!={'id','label','kind'}:
                        raise ValueError('全周热流表需要已核准实心棒的终态 Q、T 和网格')
                    checked.append(dict(**row,kind=kind,fields=['Q','T'],unit='W',time='final'))
                    continue
                if set(item)-{'id','label','field','kind','region','reduction'} or item.get('field')!='T' or kind not in ('field','profile','statistic'):
                    raise ValueError('未注册的输出定义')
                row.update(field='T',kind=kind,time='final',unit='K')
                if kind=='field':
                    if 'region' in item or 'reduction' in item:raise ValueError('原生场显示全部内部单元')
                else:
                    region=item.get('region')
                    if region not in ('fuel','cladding'):raise ValueError('输出需要明确材料区域')
                    row['region']=region
                    if kind=='statistic':
                        if item.get('reduction') not in ('min','max'):raise ValueError('需指定 min 或 max')
                        row['reduction']=item['reduction']
                    elif 'reduction' in item:raise ValueError('径向曲线保留单元采样')
            checked.append(row)
        if len({r['id'] for r in checked})!=len(checked) or key=='parameters' and len({r['binding'] for r in checked})!=len(checked):
            raise ValueError('契约中的标识或参数绑定重复')
        result[key]=checked
    result['components']=views(proposal.get('components',[]),result['outputs'],result['parameters'])
    return result
