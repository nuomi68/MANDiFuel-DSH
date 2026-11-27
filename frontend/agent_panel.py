"""Agent-defined parameters and bounded, data-only display expressions.

Parameter names are not a list of predefined features. The expression language
connects arbitrary parameter IDs to vertex coordinates and renderer primitives.
"""
import ast
import json
import math
import re

PARAMETER_TYPES={'number','range','toggle','select','color','text'}
CONTEXT={*(axis for axis in 'xyz'),*(prefix+axis for prefix in ('min','max','size','center') for axis in 'XYZ'),'pi','e','True','False'}
FUNCTIONS={'abs','min','max','sin','cos','tan','sqrt','pow','exp','log','clamp','mix','select'}
ARITY={name:(1,1) for name in ['abs','sin','cos','tan','sqrt','exp','log']}
ARITY.update(pow=(2,2),clamp=(3,3),mix=(3,3),select=(3,3),min=(1,16),max=(1,16))
STYLE_TARGETS={'scaleX','scaleY','scaleZ','opacity','palette','reversePalette','wireColor','background'}
OPTION_SPECS={'cameraView':{'auto','3d','xy','xz','yz'},'aspectMode':{'physical','fit'},'displayMode':{'surface','slice'},'sliceAxis':{'x','y','z'},'scale':{'fixed','frame'},'extremaMode':{'both','max','min'},'mesh':'bool','cut':'bool','compare':'bool','extrema':'bool','cutAngle':(0,180),'slicePosition':(0,1),'zoom':(.5,20),'yaw':(-3600,3600),'tilt':(-89,89),'time':'number','field':'field','compareField':'field','revolve':'bool','revolveAngle':(1,360)}
LANGUAGE={'version':1,'parameters':'p.<agent-defined-id>','coordinates':'source model coordinates; display only','context':sorted(CONTEXT),'functions':sorted(FUNCTIONS),'operators':['+','-','*','/','%','**','<','<=','>','>=','==','!='],'vertex':'three expressions for x, y, z','styleTargets':sorted(STYLE_TARGETS),'optionTargets':list(OPTION_SPECS),'fieldBindings':['palette','reversePalette','range'],'annotations':['point','probe','boundaryProbe','line','arrow','circle'],'boundaryProbe':'patch and field from exported shell boundaryPatches; position and value are supplied by the actual saved boundary face','probeSampling':'nearest stored cell; axisymmetric views use meridional distance'}


def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def identifier(value):return isinstance(value,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,47}',value) and value not in {'constructor','prototype','__proto__'}


def validate_view_state(state):
    if not isinstance(state,dict) or set(state)-OPTION_SPECS.keys()-{'view'}:raise ValueError('未知视图状态项')
    for key,value in state.items():
        spec=OPTION_SPECS.get(key,'view')
        if isinstance(spec,set) and (not isinstance(value,str) or value not in spec):raise ValueError('视图状态值无效：'+key)
        if isinstance(spec,tuple) and not (finite(value) and spec[0]<=value<=spec[1]):raise ValueError('视图状态超出范围：'+key)
        if spec=='bool' and not isinstance(value,bool):raise ValueError('视图状态需要布尔值：'+key)
        if spec=='number' and not finite(value):raise ValueError('视图状态需要有限数值：'+key)
        if isinstance(spec,str) and spec in {'field','view'} and (not isinstance(value,str) or len(value)>100):raise ValueError('视图标识无效')
    return dict(state)


def validate_parameter(control):
    if not isinstance(control,dict) or not identifier(control.get('id')):raise ValueError('参数需要唯一的字母开头 ID')
    kind=control.get('type')
    if kind not in PARAMETER_TYPES:raise ValueError('自定义参数需声明 number/range/toggle/select/color/text 控件类型')
    label=control.get('label',control['id'])
    if not isinstance(label,str) or len(label)>100:raise ValueError('参数名称无效')
    row={'id':control['id'],'type':kind,'label':label,'parameter':True}
    for key,limit in [('unit',40),('group',100),('help',500)]:
        if key in control:
            if not isinstance(control[key],str) or len(control[key])>limit:raise ValueError('参数说明无效')
            row[key]=control[key]
    value=control.get('default',False if kind=='toggle' else '#4477aa' if kind=='color' else '' if kind=='text' else 0)
    if kind in {'number','range'}:
        if not finite(value):raise ValueError('数字参数需要有限默认值')
        for key in ['min','max','step']:
            if key in control:
                if not finite(control[key]):raise ValueError('参数范围需要有限数值')
                row[key]=control[key]
        if kind=='range' and not {'min','max'}<=row.keys():raise ValueError('滑条需声明 min 和 max')
        if 'min' in row and 'max' in row and row['min']>=row['max']:raise ValueError('参数下限须小于上限')
        if 'step' in row and row['step']<=0:raise ValueError('参数步长须大于0')
        if value<row.get('min',-math.inf) or value>row.get('max',math.inf):raise ValueError('参数默认值超出范围')
    elif kind=='toggle':
        if not isinstance(value,bool):raise ValueError('开关参数需要布尔默认值')
    elif kind=='select':
        options=control.get('options')
        if not isinstance(options,list) or not 1<=len(options)<=100:raise ValueError('选择参数需要 options')
        row['options']=[]
        for option in options:
            if not isinstance(option,dict) or not isinstance(option.get('value'),str) or not isinstance(option.get('label'),str) or len(option['value'])>100 or len(option['label'])>100:raise ValueError('参数选项无效')
            row['options'].append({'value':option['value'],'label':option['label']})
        value=control.get('default',row['options'][0]['value'])
        if value not in [o['value'] for o in row['options']]:raise ValueError('参数默认选项不存在')
    elif kind=='color':
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('颜色参数须为 #RRGGBB')
    elif not isinstance(value,str) or len(value)>500:raise ValueError('文本参数默认值无效')
    row['default']=value
    return row


def expression_parameters(expression):
    if not isinstance(expression,str) or not 1<=len(expression)<=1200:raise ValueError('显示表达式须为1–1200字符')
    try:tree=ast.parse(expression,mode='eval')
    except (SyntaxError,ValueError,RecursionError) as error:raise ValueError('显示表达式语法无效：'+expression[:120]) from error
    if len(list(ast.walk(tree)))>160:raise ValueError('显示表达式过于复杂')
    refs=set()
    def check(node,depth=0):
        if depth>24:raise ValueError('显示表达式嵌套过深')
        if isinstance(node,ast.Expression):check(node.body,depth+1)
        elif isinstance(node,ast.Constant):
            if not (finite(node.value) or isinstance(node.value,bool) or isinstance(node.value,str) and len(node.value)<=100):raise ValueError('表达式常量无效')
            literal=ast.get_source_segment(expression,node)
            if isinstance(node.value,str) and not literal.startswith('"'):raise ValueError('表达式字符串请使用双引号')
            if isinstance(node.value,str):
                try:json.loads(literal)
                except ValueError as error:raise ValueError('表达式字符串请使用 JSON 双引号转义') from error
            if finite(node.value) and not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',literal):raise ValueError('表达式数值请使用十进制或科学计数法')
        elif isinstance(node,ast.Name):
            if node.id not in CONTEXT:raise ValueError('未知显示变量：'+node.id)
        elif isinstance(node,ast.Attribute):
            if not isinstance(node.value,ast.Name) or node.value.id!='p' or not identifier(node.attr):raise ValueError('仅支持读取 p.参数ID')
            refs.add(node.attr)
        elif isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod,ast.Pow)):
            check(node.left,depth+1);check(node.right,depth+1)
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):check(node.operand,depth+1)
        elif isinstance(node,ast.Compare) and len(node.ops)==1 and isinstance(node.ops[0],(ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.Eq,ast.NotEq)):
            check(node.left,depth+1);check(node.comparators[0],depth+1)
        elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS and not node.keywords and 1<=len(node.args)<=16:
            low,high=ARITY[node.func.id]
            if not low<=len(node.args)<=high:raise ValueError('数学函数参数数量无效：'+node.func.id)
            for arg in node.args:check(arg,depth+1)
        else:raise ValueError('表达式仅支持坐标、参数、算术和已声明数学函数')
    check(tree)
    return refs


def validate_program(program):
    if program is None:return None
    if not isinstance(program,dict) or set(program)-{'label','vertex','style','options','fields','annotations'}:raise ValueError('显示程序只支持 label、vertex、style、options、fields、annotations')
    result={}
    if 'label' in program:
        if not isinstance(program['label'],str) or len(program['label'])>100:raise ValueError('显示程序说明无效')
        result['label']=program['label']
    if 'vertex' in program:
        if not isinstance(program['vertex'],list) or len(program['vertex'])!=3:raise ValueError('顶点变换需要三个坐标表达式')
        for expression in program['vertex']:expression_parameters(expression)
        result['vertex']=list(program['vertex'])
    if 'style' in program:
        if not isinstance(program['style'],dict) or set(program['style'])-STYLE_TARGETS:raise ValueError('未知基础渲染绑定目标')
        style={}
        for target,expression in program['style'].items():
            if target in {'background','wireColor'} and isinstance(expression,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',expression):expression=json.dumps(expression)
            expression_parameters(expression);style[target]=expression
        result['style']=style
    if 'options' in program:
        if not isinstance(program['options'],dict) or set(program['options'])-OPTION_SPECS.keys():raise ValueError('未知显示选项绑定目标')
        options={}
        for target,expression in program['options'].items():
            spec=OPTION_SPECS[target]
            # Enum constants are unambiguous at these typed targets. Accept
            # their ordinary spelling as well as an explicitly quoted DSL value.
            if isinstance(spec,set) and isinstance(expression,str) and expression in spec:expression=json.dumps(expression)
            expression_parameters(expression);options[target]=expression
        result['options']=options
    if 'fields' in program:
        if not isinstance(program['fields'],dict) or len(program['fields'])>100:raise ValueError('字段显示绑定无效')
        result['fields']={}
        for ident,style in program['fields'].items():
            if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',ident) or not isinstance(style,dict) or set(style)-{'palette','reversePalette','range'}:raise ValueError('字段显示绑定无效')
            for key,expression in style.items():
                if key=='range':
                    if not isinstance(expression,list) or len(expression)!=2:raise ValueError('字段色标绑定需要两个表达式')
                    for entry in expression:expression_parameters(entry)
                else:expression_parameters(expression)
            result['fields'][ident]=dict(style)
    if 'annotations' in program:
        if not isinstance(program['annotations'],list) or not 1<=len(program['annotations'])<=12:raise ValueError('标注列表无效')
        rows=[];seen=set()
        for annotation in program['annotations']:
            if not isinstance(annotation,dict) or set(annotation)-{'id','type','label','position','end','text','color','visible','field','radius','axis','views','patch'}:raise ValueError('标注定义无效')
            if not identifier(annotation.get('id')) or annotation['id'] in seen or annotation.get('type') not in {'point','probe','line','arrow','circle','boundaryProbe'}:raise ValueError('标注 ID 或类型无效')
            if annotation['type']=='boundaryProbe':
                if not isinstance(annotation.get('patch'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',annotation['patch']) or any(k in annotation for k in ('position','text','end')):
                    raise ValueError('边界测点仅接受实际 patch 名称，位置与值由原始边界提供')
            elif 'patch' in annotation:
                raise ValueError('仅边界测点可指定 patch')
            if 'views' in annotation and (not isinstance(annotation['views'],list) or not 1<=len(annotation['views'])<=20 or not all(isinstance(v,str) and 0<len(v)<=100 for v in annotation['views'])):raise ValueError('标注视图范围无效')
            if annotation['type']=='circle':
                expression_parameters(annotation.get('radius'))
                if annotation.get('axis','y') not in {'x','y','z'}:raise ValueError('圆形导引平面无效')
            elif 'radius' in annotation or 'axis' in annotation:raise ValueError('半径和平面只适用于 circle 导引')
            seen.add(annotation['id'])
            if 'label' in annotation and (not isinstance(annotation['label'],str) or len(annotation['label'])>100):raise ValueError('标注名称无效')
            for key in ([] if annotation['type']=='boundaryProbe' else ['position',*(['end'] if annotation['type'] in {'line','arrow'} else [])]):
                if not isinstance(annotation.get(key),list) or len(annotation[key])!=3:raise ValueError('标注位置需要三个坐标表达式')
                for expression in annotation[key]:expression_parameters(expression)
            annotation=dict(annotation)
            if isinstance(annotation.get('color'),str) and re.fullmatch(r'#[0-9a-fA-F]{6}',annotation['color']):annotation['color']=json.dumps(annotation['color'])
            for key in ['text','color','visible']:
                if key in annotation:expression_parameters(annotation[key])
            if 'field' in annotation and (not isinstance(annotation['field'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',annotation['field'])):raise ValueError('标注字段无效')
            rows.append(dict(annotation))
        result['annotations']=rows
    if not any(result.get(key) for key in ['vertex','style','options','fields','annotations']):raise ValueError('显示程序需要至少一项实际绑定')
    return result


def program_parameters(program):
    if not program:return set()
    refs=set()
    for expression in program_expressions(program):refs.update(expression_parameters(expression))
    return refs


def program_expressions(program):
    expressions=[*program.get('vertex',[]),*program.get('style',{}).values(),*program.get('options',{}).values()]
    for style in program.get('fields',{}).values():
        for key,value in style.items():expressions.extend(value if key=='range' else [value])
    for annotation in program.get('annotations',[]):
        expressions.extend(annotation.get('position',[]));expressions.extend(annotation.get('end',[]))
        expressions.extend(annotation[key] for key in ['text','color','visible','radius'] if key in annotation)
    return expressions


def parameter_state(previous,update):
    """Preserve edited values unless the agent explicitly changes their definition."""
    if 'parameterValues' not in update and ('controls' not in update or update['controls']==previous.get('controls')):return None
    old={c['id']:c for c in previous.get('controls',[]) if c.get('parameter')}
    controls={c['id']:c for c in update.get('controls',previous.get('controls',[])) if c.get('parameter')}
    values={}
    for ident,control in controls.items():
        value=previous.get('parameterValues',{}).get(ident,control['default'])
        if ident not in old or control['default']!=old[ident]['default']:value=control['default']
        try:validate_parameter({**control,'default':value})
        except ValueError:value=control['default']
        values[ident]=value
    for ident,value in update.get('parameterValues',{}).items():
        if ident not in controls:raise ValueError('未定义参数：'+str(ident)+'；基础显示项请使用 viewState 或控件 default，不要放入 parameterValues')
        validate_parameter({**controls[ident],'default':value});values[ident]=value
    return values


def check_program_values(program,values,bounds=None):
    """Check current parameters at bounds and centre without executing code."""
    if not program:return
    bounds=bounds or {'min':[-1,-1,-1],'max':[1,1,1]}
    context={}
    for i,a in enumerate('XYZ'):
        lo,hi=bounds['min'][i],bounds['max'][i]
        context.update({'min'+a:lo,'max'+a:hi,'size'+a:hi-lo,'center'+a:(lo+hi)/2})
    functions={name:getattr(math,name) for name in ['sin','cos','tan','sqrt','exp','log','pow']}
    functions.update(abs=abs,min=lambda *v:min(v),max=lambda *v:max(v),clamp=lambda v,a,b:max(a,min(b,v)),mix=lambda a,b,t:a+(b-a)*t)
    def evaluate(node,point):
        if isinstance(node,ast.Expression):return evaluate(node.body,point)
        if isinstance(node,ast.Constant):return float(node.value) if finite(node.value) else node.value
        if isinstance(node,ast.Name):return {'pi':math.pi,'e':math.e,**context,**point}[node.id]
        if isinstance(node,ast.Attribute):return values[node.attr]
        if isinstance(node,ast.UnaryOp):
            value=evaluate(node.operand,point)
            if not finite(value):raise ValueError('算术表达式需要数值参数')
            return -value if isinstance(node.op,ast.USub) else value
        if isinstance(node,ast.BinOp):
            a,b=evaluate(node.left,point),evaluate(node.right,point)
            if not finite(a) or not finite(b):raise ValueError('算术表达式需要数值参数')
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div):return a/b
            if isinstance(node.op,ast.Mod):return math.fmod(a,b)
            return math.pow(a,b)
        if isinstance(node,ast.Compare):
            a,b=evaluate(node.left,point),evaluate(node.comparators[0],point);op=node.ops[0]
            if isinstance(op,ast.Eq):return a==b
            if isinstance(op,ast.NotEq):return a!=b
            if isinstance(op,ast.Lt):return a<b
            if isinstance(op,ast.LtE):return a<=b
            if isinstance(op,ast.Gt):return a>b
            return a>=b
        if isinstance(node,ast.Call):
            if node.func.id=='select':return evaluate(node.args[1 if evaluate(node.args[0],point) else 2],point)
            args=[evaluate(n,point) for n in node.args]
            if not all(finite(v) for v in args):raise ValueError('数学函数需要数值参数')
            return functions[node.func.id](*args)
        raise ValueError('不支持的显示表达式')
    try:
        option_values={}
        expressions=[ast.parse(e,mode='eval') for e in program.get('vertex',[])]
        positions=[bounds['min'],bounds['max'],[(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]]
        for position in positions:
            point=dict(zip('xyz',position))
            for expression in expressions:
                value=evaluate(expression,point)
                if not finite(value) or abs(value)>1e12:raise ValueError('显示程序产生无效坐标')
        for target,source in program.get('style',{}).items():
            value=evaluate(ast.parse(source,mode='eval'),dict(zip('xyz',positions[-1])))
            if target in {'scaleX','scaleY','scaleZ'} and not (finite(value) and .01<=value<=100):raise ValueError('缩放绑定超出范围')
            if target=='opacity' and not (finite(value) and .05<=value<=1):raise ValueError('透明度绑定超出范围')
            if target in {'background','wireColor'} and not (isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)):raise ValueError('颜色绑定无效')
            if target=='palette' and value not in {'coolwarm','viridis','inferno','gray','rainbow'}:raise ValueError('命名色带绑定无效')
            if target=='reversePalette' and not isinstance(value,bool):raise ValueError('布尔绑定无效')
        for target,source in program.get('options',{}).items():
            value=evaluate(ast.parse(source,mode='eval'),dict(zip('xyz',positions[-1])));spec=OPTION_SPECS[target]
            option_values[target]=value
            if isinstance(spec,set) and value not in spec:raise ValueError('显示选项绑定值无效：'+target)
            if isinstance(spec,tuple) and not (finite(value) and spec[0]<=value<=spec[1]):raise ValueError('显示选项超出范围：'+target)
            if spec=='bool' and not isinstance(value,bool):raise ValueError('显示选项需要布尔值：'+target)
            if spec=='number' and not finite(value):raise ValueError('显示选项需要有限数值：'+target)
            if spec=='field' and not isinstance(value,str):raise ValueError('显示选项需要实际字段 ID：'+target)
        for style in program.get('fields',{}).values():
            evaluated={key:[evaluate(ast.parse(e,mode='eval'),dict(zip('xyz',positions[-1]))) for e in value] if key=='range' else evaluate(ast.parse(value,mode='eval'),dict(zip('xyz',positions[-1]))) for key,value in style.items()}
            if 'range' in evaluated and not (all(finite(v) for v in evaluated['range']) and evaluated['range'][0]<evaluated['range'][1]):raise ValueError('字段色标下限须小于上限')
            if 'palette' in evaluated and evaluated['palette'] not in {'coolwarm','viridis','inferno','gray','rainbow'}:raise ValueError('字段命名色带无效')
            if 'reversePalette' in evaluated and not isinstance(evaluated['reversePalette'],bool):raise ValueError('字段色带反转需要布尔值')
        for annotation in program.get('annotations',[]):
            for key in [k for k in ('position','end') if k in annotation]:
                for source in annotation[key]:
                    value=evaluate(ast.parse(source,mode='eval'),dict(zip('xyz',positions[-1])))
                    if not finite(value) or abs(value)>1e12:raise ValueError('标注坐标无效')
            if 'visible' in annotation and not isinstance(evaluate(ast.parse(annotation['visible'],mode='eval'),dict(zip('xyz',positions[-1]))),bool):raise ValueError('标注可见性需为布尔值')
            if 'text' in annotation:
                value=evaluate(ast.parse(annotation['text'],mode='eval'),dict(zip('xyz',positions[-1])))
                if not isinstance(value,(str,int,float)) or isinstance(value,str) and len(value)>500:raise ValueError('标注文字无效')
            if 'color' in annotation:
                value=evaluate(ast.parse(annotation['color'],mode='eval'),dict(zip('xyz',positions[-1])))
                if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('标注颜色无效')
        return {'options':option_values}
    except (ArithmeticError,KeyError,TypeError,ValueError) as error:raise ValueError('显示程序与当前参数不匹配：'+str(error)) from error
