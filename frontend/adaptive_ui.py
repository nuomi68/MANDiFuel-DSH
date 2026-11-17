"""A bounded component catalog: agents compose pages, never executable markup."""
import copy
import csv
import json
import math
import re
from pathlib import Path
from functools import lru_cache
from agent_panel import identifier, expression_parameters, validate_view_state
from chart_schema import CHARTS,COMMON,validate_chart,validate_table

CATALOG = {
    'version': 1,
    'policy':{'scalarCards':False,'duplicateWindows':'exact duplicate content is removed','modelWindow':'retained from mesh preview through saved fields','workflowProgress':'read-only process-observer'},
    'document': {'version': 1, 'mode': ['above', 'below', 'replace'], 'root': 'main component tree', 'aside':'optional component tree below DSH chat; moves below main content when chat is closed or on mobile', 'scope':['all','overview','model'], 'datasets': {'id': {'file': 'workspace-relative JSON or CSV with a header; optional rows:path and columns:[{id,path,label,unit}] map ordinary terminal records without changing source; CSV uses its actual header IDs, finite numeric cells and null for empty cells'}}},
    'containers': {'row': 'children', 'column': 'children', 'grid': 'columns 1–4, children', 'tabs': 'children with titles'},
    'components': {
        'chart': 'mixed scientific marks: series [{label,source,x?,y?,mark:line|scatter|bar|interval,color?,dash:solid|dash|dot,marker:none|circle|square|triangle|diamond,width?,size?,opacity?,step?,order:source|x,xLow?,xHigh?,yLow?,yHigh?}]; xAxis/yAxis:{label?,scale:linear|log,min?,max?,reverse?,grid?,ticks?:numeric array}; references:[{axis:x|y,value or from/to,label?,color?,dash?,opacity?}]; height:220–800,legend:bottom|right|none,caption?',
        'lineChart': 'same as chart; default line mark',
        'barChart': 'same as chart; default bar mark, supports categorical x',
        'intervalChart': 'same as chart; requires real paired xLow/xHigh or yLow/yHigh columns',
        'heatmapChart': 'source,x,y,value column IDs; palette?,colorRange?:[min,max],showValues?,xLabel?,yLabel?,xAxis/yAxis?,height?,caption?; duplicate grid points rejected, missing cells stay missing',
        'scatterChart': 'same as lineChart',
        'table': 'title,source,columns?:[ID or {id,label?,unit?,format:auto|fixed|scientific,digits:0–12,align:left|center|right}],searchable?,sort:{column,direction:asc|desc},highlight:{column,mode:min|max},pageSize:10–200',
        'text': 'text (plain text)', 'controls': 'title, ids:[existing control IDs], placement:settings(default)|inline(only when user requests controls beside results)',
        'image':'file:workspace-relative PNG/JPEG/WebP, alt, caption?; display an existing verified image, never invent scientific results',
        'button': 'label, action:{type:view,state:{...}} or {type:parameter,id,value}',
        'model': 'existing model viewport; at most one, state?:one-shot viewState',
    },
    'sources': {
        'profile': 'field: actual exported field ID or selected; rows x/value from saved cell centres, no CSV required; axis:cell|r|x|y|z (r is cylindrical radius about the reconstruction axis, otherwise z); time:current|saved time, view?:actual view ID; physical coordinate units come from mesh metadata',
        'history': 'field, statistic:min|max|mean, view?',
        'probeHistory': 'field, position:[three bounded expressions, e.g. p.sampleX], view?; nearest stored cell',
        'study': 'status:completed(default)|all|queued|running|failed|skipped; best?:objective response ID adds only best.<objective ID>; select:best with best:<objective ID> returns the best feasible run, using its parameter.<id>/response.<id> columns; filter?:[{column,op:eq|ne|lt|lte|gt|gte,value}]; columns record/runId/label/status(localized display)/statusCode(raw code)/iteration/caseRoot plus parameter.<id> and response.<id>; no model required',
        'dataset': 'dataset: ID declared in document.datasets; runId?:actual column containing real study run IDs enables linked chart/table selection and model navigation; optional rows/columns path mapping reads ordinary JSON records; table file {columns:[{id,label?,unit?}],rows:[objects]}',
    },
    'bindings': 'visible: bounded boolean expression; probe coordinates may reference p.<control ID>',
    'limits': {'nodes': 64, 'depth': 8, 'seriesPerChart': 12, 'datasets': 8, 'rowsPerDataset': 20000, 'bytesPerDataset': 2*1024*1024},
    'codeExecution': False,
}
CONTAINERS = {'row', 'column', 'grid', 'tabs'}
TYPES = CONTAINERS | set(CATALOG['components']) | {'metric'}  # Legacy data is cleaned before rendering.


def fail(message): raise ValueError('展示面板：'+message)
def string(value, limit=120):
    if not isinstance(value, str) or len(value)>limit: fail('文本或标识长度无效')
    return value
def number(value): return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)


def validate_source(source):
    if not isinstance(source,dict): fail('数据源必须是对象')
    kind=source.get('kind')
    allowed={'study':{'kind','status','best','select'},'dataset':{'kind','dataset','runId'},'profile':{'kind','view','field','axis','time'},'history':{'kind','view','field','statistic'},'probeHistory':{'kind','view','field','position'}}.get(kind,set())
    allowed|={'filter'}
    filters=source.get('filter',[])
    if not isinstance(filters,list) or len(filters)>8:fail('数据筛选条件无效')
    for row in filters:
        if not isinstance(row,dict) or set(row)!={'column','op','value'} or row['op'] not in {'eq','ne','lt','lte','gt','gte'} or not (number(row['value']) or isinstance(row['value'],str)):fail('数据筛选条件无效')
        string(row['column'])
    if kind not in CATALOG['sources'] or set(source)-allowed: fail('未知数据源或数据源属性')
    result=copy.deepcopy(source)
    if kind=='study':
        if 'best' in source:string(source['best'])
        if source.get('status','completed') not in {'all','completed','queued','running','failed','skipped'}:fail('研究状态筛选无效')
        if 'select' in source and (source['select']!='best' or not source.get('best') or source.get('status','completed') not in {'all','completed'}):fail('选择最好工况需要 best 目标及 completed/all 状态')
        for rule in filters:
            if rule['column']=='status' and rule['value'] not in {'等待','执行中','已完成','失败','跳过'}:fail('status 是中文显示文字；筛选状态代码请使用 source.status 或 statusCode 列')
        return result
    if kind=='dataset':
        if not identifier(source.get('dataset')): fail('数据表 ID 无效')
        if 'runId' in source:string(source['runId'])
        return result
    string(source.get('field'))
    if 'view' in source: string(source['view'])
    if kind=='profile':
        if source.get('axis','cell') not in {'cell','r','x','y','z'}: fail('剖面坐标轴无效')
        if source.get('time','current')!='current' and not number(source['time']): fail('保存时间无效')
    if kind=='history' and source.get('statistic','max') not in {'min','max','mean'}: fail('历史统计量无效')
    if kind=='probeHistory':
        if not isinstance(source.get('position'),list) or len(source['position'])!=3: fail('测点需要三个坐标表达式')
        for expression in source['position']: expression_parameters(expression)
    return result


def validate_ui(document):
    if document is None:return None
    if not isinstance(document,dict) or set(document)-{'version','mode','scope','root','aside','datasets'} or document.get('version')!=1: fail('界面文档版本或属性无效')
    document=copy.deepcopy(document)
    if document.get('mode','above') not in {'above','below','replace'}: fail('布局位置无效')
    if document.get('scope','all') not in {'all','overview','model'}:fail('界面适用区域无效')
    datasets=document.get('datasets',{})
    if not isinstance(datasets,dict) or len(datasets)>8: fail('最多使用八份数据表')
    for ident,spec in datasets.items():
        if not identifier(ident) or not isinstance(spec,dict) or set(spec)-{'file','rows','columns'} or 'file' not in spec: fail('数据表声明无效')
        path=Path(string(spec['file'],500))
        if path.is_absolute() or '..' in path.parts or path.suffix.lower() not in {'.json','.csv'}: fail('数据表必须是工作区内的 JSON 或 CSV 文件')
        if 'columns' in spec and 'rows' not in spec and path.suffix.lower()=='.csv':spec['rows']='rows'
        if ('rows' in spec)!=('columns' in spec):fail('记录表映射需要 rows 与 columns；普通 CSV 可只提供 file，或用 columns 指定实际表头与格式')
        if 'rows' in spec:
            string(spec['rows'],300)
            if not isinstance(spec['columns'],list) or not 1<=len(spec['columns'])<=32:fail('记录表映射列无效')
            spec['columns']=[{'id':c} if isinstance(c,str) else c for c in spec['columns']]
            ids=set()
            for c in spec['columns']:
                if not isinstance(c,dict) or set(c)-{'id','label','unit','path'} or not isinstance(c.get('id'),str) or not c['id'] or c['id'] in ids:fail('记录表映射列无效')
                ids.add(c['id'])
                for value in c.values():string(value,300)
    seen=set(); model_count=0
    def visit(node,depth=0):
        nonlocal model_count
        if not isinstance(node,dict) or not identifier(node.get('id')) or node['id'] in seen: fail('组件需要唯一 ID')
        seen.add(node['id'])
        if len(seen)>64 or depth>8: fail('组件数量或嵌套层数超出限制')
        kind=node.get('type')
        def node_source(source):
            try:return validate_source(source)
            except ValueError as error:raise ValueError('展示组件 '+node['id']+'：'+str(error)) from error
        if kind not in TYPES: fail('未注册的组件类型：'+str(kind))
        allowed={'id','type','title','visible'}
        if 'title' in node:string(node['title'])
        if 'visible' in node:expression_parameters(node['visible'])
        if kind in CONTAINERS:
            allowed|={'children'}
            if kind=='grid':allowed.add('columns')
            if not isinstance(node.get('children'),list) or not node['children']:fail('布局需要至少一个子组件')
            if 'columns' in node and (type(node['columns']) is not int or not 1<=node['columns']<=4):fail('网格列数须为 1–4')
            for child in node['children']:visit(child,depth+1)
        elif kind in CHARTS:
            allowed|=COMMON|({'source','x','y','value','palette','colorRange','showValues','valueDigits'} if kind=='heatmapChart' else {'series'})
            validate_chart(node,node_source)
        elif kind in {'table','metric'}:
            allowed|={'source'}|({'columns','pageSize','searchable','sort','highlight'} if kind=='table' else {'column','reducer','unit'});node_source(node.get('source'))
            if kind=='table':validate_table(node)
            if node.get('reducer','last') not in {'last','min','max','mean'}:fail('指标归约方式无效')
            for key in ['column','unit']:
                if key in node:string(node[key])
        elif kind=='text':allowed.add('text');string(node.get('text'),4000)
        elif kind=='image':
            allowed|={'file','alt','caption'};image_path=Path(string(node.get('file'),500));string(node.get('alt'),500)
            if image_path.is_absolute() or '..' in image_path.parts or image_path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:fail('图片需要工作区内的 PNG/JPEG/WebP 文件')
            if 'caption' in node:string(node['caption'],1000)
        elif kind=='controls':
            allowed|={'ids','placement'}
            if node.get('placement','settings') not in {'settings','inline'}:fail('控件位置须为 settings 或 inline')
            if not isinstance(node.get('ids'),list) or len(node['ids'])>100 or not all(identifier(i) for i in node['ids']):fail('参数组引用无效')
        elif kind=='button':
            allowed|={'label','action'};string(node.get('label'));action=node.get('action')
            if not isinstance(action,dict):fail('按钮动作无效')
            if action.get('type')=='view' and set(action)=={'type','state'}:validate_view_state(action['state'])
            elif action.get('type')=='parameter' and set(action)=={'type','id','value'} and identifier(action['id']):pass
            else:fail('未注册的按钮动作')
        elif kind=='model':
            allowed.add('state');model_count+=1
            if model_count>1:fail('同一布局只挂载一个主模型，变量并排请使用比较功能')
            if 'state' in node:validate_view_state(node['state'])
        if set(node)-allowed:fail('组件 '+node['id']+'（'+kind+'）含未支持的属性：'+', '.join(sorted(set(node)-allowed)))
    visit(document.get('root'))
    if 'aside' in document:visit(document['aside'])
    return copy.deepcopy(document)


def walk_ui(document):
    if not document:return
    pending=[document['root']]+([document['aside']] if document.get('aside') else [])
    while pending:
        node=pending.pop();yield node;pending.extend(reversed(node.get('children',[])))


def ui_sources(document):
    for node in walk_ui(document):
        if 'source' in node:yield node['source']
        for series in node.get('series',[]):yield series['source']


def ui_parameters(document):
    refs=set()
    for node in walk_ui(document):
        if 'visible' in node:refs.update(expression_parameters(node['visible']))
    for source in ui_sources(document):
        for expression in source.get('position',[]):refs.update(expression_parameters(expression))
    return refs


def load_dataset(workspace,spec):
    root=Path(workspace).resolve();path=(root/spec['file']).resolve()
    if not path.is_relative_to(root) or not path.is_file():fail('数据表不在本任务工作区或文件不存在')
    stat=path.stat()
    if stat.st_size>2*1024*1024:fail('单份数据表不能超过 2 MB')
    return read_dataset(str(path),stat.st_mtime_ns,stat.st_size,json.dumps({k:v for k,v in spec.items() if k!='file'},sort_keys=True))


@lru_cache(maxsize=8)
def read_dataset(filename,mtime,size,mapping='{}'):
    path=Path(filename)
    if path.suffix.lower()=='.csv':
        def cell(value):
            stripped=value.strip()
            if not stripped:return None
            if stripped.lower() in {'nan','+nan','-nan','inf','+inf','-inf','infinity','+infinity','-infinity'}:fail('数据值只能是有限数字、文字或空值')
            if not re.fullmatch(r'[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',stripped):return value
            parsed=float(stripped)
            if not math.isfinite(parsed):fail('数据值只能是有限数字、文字或空值')
            if re.fullmatch(r'[+-]?\d+',stripped):
                integer=int(stripped)
                return integer if abs(integer)<=2**53-1 else value
            return parsed
        try:
            with path.open(encoding='utf-8-sig',newline='') as handle:
                reader=csv.reader(handle,strict=True);header=next(reader,[])
                if not header or any(not name for name in header) or len(set(header))!=len(header):fail('CSV 表头不能为空或重复')
                rows=[]
                for row in reader:
                    if not row:continue
                    if len(row)!=len(header):fail('CSV 数据行与表头列数不一致')
                    if len(rows)>=20000:fail('数据表列数或行数超出限制')
                    rows.append(dict(zip(header,map(cell,row))))
                table={'columns':header,'rows':rows}
        except (csv.Error,UnicodeError) as error:raise ValueError('展示面板：数据表不是有效 CSV') from error
    else:
        try:table=json.loads(path.read_text())
        except (ValueError,UnicodeError) as error:raise ValueError('展示面板：数据表不是有效 JSON') from error
    spec=json.loads(mapping)
    if 'rows' in spec:
        if path.suffix.lower()=='.csv':
            known=set(table['columns'])
            for column in spec['columns']:
                source=column.get('path',column['id'])
                if source not in known:fail('CSV 数据列不存在：'+source)
        def get(value,path):
            if isinstance(value,dict) and path in value:return value[path]
            for part in path.split('.') if path else []:
                if isinstance(value,dict):value=value.get(part)
                elif isinstance(value,list) and part.isdigit() and int(part)<len(value):value=value[int(part)]
                else:return None
            return value
        records=get(table,spec['rows'])
        if not isinstance(records,list) or len(records)>20000 or any(not isinstance(row,dict) for row in records):fail('记录表路径必须指向真实记录数组')
        table={'columns':[{k:v for k,v in c.items() if k!='path'} for c in spec['columns']],'rows':[{c['id']:get(row,c.get('path',c['id'])) for c in spec['columns']} for row in records]}
    if not isinstance(table,dict) or set(table)-{'columns','rows'}:fail('数据表需要 columns 与 rows')
    columns=table.get('columns');rows=table.get('rows')
    if not isinstance(columns,list) or not 1<=len(columns)<=32 or not isinstance(rows,list) or len(rows)>20000:fail('数据表列数或行数超出限制')
    clean=[];seen=set()
    for column in columns:
        if isinstance(column,str):column={'id':column}
        if not isinstance(column,dict) or set(column)-{'id','label','unit'}:fail('数据列声明无效')
        ident=string(column.get('id'))
        if not ident or ident in seen:fail('数据列 ID 不能为空或重复')
        seen.add(ident);clean.append({k:string(v) for k,v in column.items()})
    for row in rows:
        if not isinstance(row,dict) or set(row)-seen:fail('数据行引用未知列')
        for value in row.values():
            if value is not None and not number(value) and not isinstance(value,str):fail('数据值只能是有限数字、文字或空值')
            if isinstance(value,str) and len(value)>2000:fail('数据单元格文字过长')
    return {'columns':clean,'rows':rows,'version':f'{mtime}-{size}'}


def validate_ui_delivery(document,views,preferred,controls,workspace=None,study=None):
    if not document:return
    by_id={c['id']:c for c in controls};params={c['id'] for c in controls if c.get('parameter')}
    missing=ui_parameters(document)-params
    if missing:fail('引用未定义参数：'+', '.join(sorted(missing)))
    datasets=document.get('datasets',{})
    tables={ident:load_dataset(workspace,spec) for ident,spec in datasets.items()} if workspace is not None else {}
    def columns(source):
        if source['kind']=='study':
            return {'record','runId','label','status','statusCode','iteration','caseRoot'}|{'parameter.'+d['id'] for d in study['parameters']}|{'response.'+d['id'] for d in study['responses']}|({'best.'+source['best']} if source.get('best') else set())
        if source['kind']=='dataset':
            table=tables.get(source['dataset'])
            spec=datasets.get(source['dataset'],{})
            actual={c['id'] for c in table['columns']} if table else {c['id'] for c in spec['columns']} if 'columns' in spec else None
            return actual|{'runId'} if actual is not None and source.get('runId') else actual
        return {'x','value'}|({'cell','distance'} if source['kind']=='probeHistory' else set())
    def check_columns(source,refs):
        actual=columns(source)
        if actual is not None and set(refs)-actual:fail('引用不存在的数据列：'+', '.join(sorted(set(refs)-actual))+'；实际列：'+', '.join(sorted(actual)))
    for source in ui_sources(document):
        if source['kind']=='study':
            if not study:fail('研究数据源尚无真实研究记录')
            if source.get('best') and not any(d['id']==source['best'] and d.get('goal') in {'min','max'} for d in study['responses']):fail('最好值需要有实际目标方向的响应')
            continue
        if source['kind']=='dataset':
            if source['dataset'] not in datasets:fail('引用未声明的数据表')
            if source.get('runId'):
                if not study:fail('工况关联需要真实研究记录')
                table=tables.get(source['dataset'])
                if table:
                    if source['runId'] not in {c['id'] for c in table['columns']}:fail('工况关联引用不存在的数据列')
                    ids={r['id'] for r in study['runs']}
                    if any(row.get(source['runId']) is not None and row[source['runId']] not in ids for row in table['rows']):fail('工况关联引用未知的真实工况 ID')
            continue
        view=source.get('view',preferred)
        if view not in views:fail('数据源引用尚未交付的模型视图')
        meta=views[view]['task'];fields={f['id'] for f in meta.get('fields',[])}
        if source['field']!='selected' and source['field'] not in fields:fail('数据源引用不存在的物理量：'+source['field'])
        if not fields:fail('网格预览没有结果场可供绘图')
        if source['kind']=='probeHistory' and not meta.get('supportsExtrema'):fail('测点历史需要真实单元中心')
    for source in ui_sources(document):check_columns(source,[rule['column'] for rule in source.get('filter',[])])
    for node in walk_ui(document):
        if node['type']=='image' and workspace is not None:image_file(workspace,node['file'])
        if node['type']=='metric':check_columns(node['source'],[node.get('column','value')])
        elif node['type']=='heatmapChart':check_columns(node['source'],[node['x'],node['y'],node['value']])
        elif node['type'] in CHARTS:
            for s in node['series']:
                refs=[s.get('x','x')] if 'xLow' not in s else [s['xLow'],s['xHigh']]+([s['x']] if 'x' in s else [])
                refs+=([s.get('y','value')] if 'yLow' not in s else [s['yLow'],s['yHigh']]+([s['y']] if 'y' in s else []))
                check_columns(s['source'],refs)
        elif node['type']=='table':
            refs=[c if isinstance(c,str) else c['id'] for c in node.get('columns',[])]
            refs+=[node[key]['column'] for key in ['sort','highlight'] if key in node]
            check_columns(node['source'],refs)
        if node['type']=='controls' and set(node['ids'])-by_id.keys():fail('参数组引用未定义控件')
        actions=[node['action']] if node['type']=='button' else [{'type':'view','state':node['state']}] if node['type']=='model' and node.get('state') else []
        for action in actions:
            if action['type']=='parameter':
                if action['id'] not in params:fail('按钮引用未定义参数')
                from agent_panel import validate_parameter
                validate_parameter({**by_id[action['id']],'default':action['value']})
            else:
                state=action['state'];view=state.get('view',preferred)
                if view not in views:fail('按钮或模型引用尚未交付的视图')
                fields={f['id'] for f in views[view]['task'].get('fields',[])}
                if any(state.get(k) not in fields for k in ['field','compareField'] if k in state):fail('按钮引用不存在的物理量')


def image_file(workspace,relative):
    root=Path(workspace).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>10*1024*1024:fail('图片不存在、越出工作区或超过 10 MB')
    prefix=path.read_bytes()[:16]
    valid=path.suffix.lower()=='.png' and prefix.startswith(b'\x89PNG\r\n\x1a\n') or path.suffix.lower() in {'.jpg','.jpeg'} and prefix.startswith(b'\xff\xd8\xff') or path.suffix.lower()=='.webp' and prefix.startswith(b'RIFF') and prefix[8:12]==b'WEBP'
    if not valid:fail('图片内容与声明格式不符')
    return path
