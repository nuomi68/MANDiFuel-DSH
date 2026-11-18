"""Validate bounded browser observations, never executable DOM or chat content."""
import json
import math


def validate_observation(state):
    def numeric(value):return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and abs(value)<=1e7
    def text(value,limit=200):return isinstance(value,str) and len(value)<=limit
    def rect(value):return isinstance(value,dict) and set(value)=={'x','y','width','height'} and all(numeric(v) for v in value.values()) and value['width']>=0 and value['height']>=0
    if 'browserId' in state and (not text(state['browserId'],64) or not state['browserId']):raise ValueError('浏览器标识无效')
    if len(json.dumps(state,ensure_ascii=False,allow_nan=False))>65536:raise ValueError('前端状态快照过大')
    if 'presentationVersion' in state and (type(state['presentationVersion']) is not int or state['presentationVersion']<0):raise ValueError('前端显示版本无效')
    if 'interactionRevision' in state and (type(state['interactionRevision']) is not int or state['interactionRevision']<0):raise ValueError('前端交互版本无效')
    if 'ready' in state and type(state['ready']) is not bool:raise ValueError('前端就绪状态无效')
    if 'viewport' in state:
        value=state['viewport']
        if not isinstance(value,dict) or set(value)-{'width','height','dpr','scrollX','scrollY'} or not {'width','height'}<=value.keys() or not all(numeric(v) for v in value.values()):raise ValueError('页面尺寸观察无效')
    if 'slots' in state:
        slots=state['slots']
        if not isinstance(slots,dict) or set(slots)-{'main','aside','settings','model','conversation','evidence'}:raise ValueError('插槽观察无效')
        for value in slots.values():
            if not isinstance(value,dict) or set(value)!={'visible','rect'} or type(value['visible']) is not bool or not rect(value['rect']):raise ValueError('插槽布局观察无效')
    if 'nodes' in state:
        nodes=state['nodes']
        if not isinstance(nodes,list) or len(nodes)>64:raise ValueError('组件观察数量无效')
        for node in nodes:
            if not isinstance(node,dict) or set(node)-{'id','type','visible','rect','activeTab','table','chart','inViewport','coveredBy'} or not text(node.get('id'),100) or not text(node.get('type'),40) or type(node.get('visible')) is not bool or not rect(node.get('rect')):raise ValueError('组件观察无效')
            if 'inViewport' in node and type(node['inViewport']) is not bool:raise ValueError('视口可见性观察无效')
            if 'coveredBy' in node and (not isinstance(node['coveredBy'],list) or len(node['coveredBy'])>3 or not all(text(v,100) for v in node['coveredBy'])):raise ValueError('窗口遮挡观察无效')
            if 'activeTab' in node and not text(node['activeTab'],100):raise ValueError('当前页签观察无效')
            if 'table' in node:
                value=node['table']
                if not isinstance(value,dict) or set(value)-{'query','page','rows','sort'} or not text(value.get('query','')) or any(type(value.get(k,0)) is not int or not 0<=value.get(k,0)<=20000 for k in ('page','rows')):raise ValueError('表格交互观察无效')
                sort=value.get('sort')
                if sort is not None and (not isinstance(sort,dict) or set(sort)!={'column','direction'} or not text(sort['column'],300) or sort['direction'] not in {'asc','desc'}):raise ValueError('表格排序观察无效')
            if 'chart' in node:
                value=node['chart']
                if not isinstance(value,dict) or set(value)-{'viewport','hiddenSeries'} or not isinstance(value.get('hiddenSeries',[]),list) or len(value.get('hiddenSeries',[]))>12 or not all(type(v) is int and 0<=v<12 for v in value.get('hiddenSeries',[])):raise ValueError('图表交互观察无效')
                # Domains are data, bounded recursively rather than evaluated.
                if len(json.dumps(value.get('viewport')))>1000:raise ValueError('图表显示范围观察过大')
    if 'selection' in state:
        value=state['selection']
        if not isinstance(value,dict) or set(value)-{'run','panel','field','view','frame','time','timeUnit','settingsOpen'} or any(not (v is None or isinstance(v,bool) or type(v) is int and 0<=v<=100000 or text(v,100)) for k,v in value.items() if k!='time') or ('time' in value and (type(value['time']) not in (int,float) or not math.isfinite(value['time']))):raise ValueError('页面选择状态无效')
    if state.get('pickedPoint') is not None:
        point=state['pickedPoint']
        if not isinstance(point,dict) or set(point)!={'position','view','time','timeUnit','field'} or not isinstance(point['position'],list) or len(point['position'])!=3 or not all(numeric(v) for v in point['position']) or not numeric(point['time']) or any(not text(point[k],100) for k in ['view','timeUnit','field']):raise ValueError('选中位置观察无效')
    if 'parameters' in state:
        value=state['parameters']
        if not isinstance(value,dict) or len(value)>100 or any(not text(k,64) or not (isinstance(v,bool) or isinstance(v,(int,float)) and math.isfinite(v) or text(v,500)) for k,v in value.items()):raise ValueError('前端参数观察无效')
    if 'model' in state:
        value=state['model']
        if not isinstance(value,dict) or set(value)!={'visible','ready','kind','view','field'} or type(value['visible']) is not bool or type(value['ready']) is not bool or value['kind'] not in {'pending','mesh','fields'} or any(v is not None and not text(v,100) for v in [value['view'],value['field']]):raise ValueError('物理场窗口观察无效')
    if 'display' in state:
        value=state['display']
        if not isinstance(value,dict) or set(value)-{'mesh','extrema','cut','cutAngle','cameraView','aspectMode','displayMode','sliceAxis','slicePosition','compare','compareField','scale','colorMin','colorMax','appearance','fieldMapping'} or len(json.dumps(value))>5000:raise ValueError('前端实际显示状态无效')
