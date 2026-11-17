"""Data-only interaction commands for existing owned components."""
import math
from adaptive_ui import walk_ui
from chart_schema import CHARTS


def validate_interactions(actions,document=None,*,check_targets=False):
    if not isinstance(actions,list) or len(actions)>24:raise ValueError('交互操作数量无效')
    nodes={node['id']:node for node in walk_ui(document)} if document else {} if check_targets else None
    for action in actions:
        if not isinstance(action,dict) or set(action)!={'id','state'} or not isinstance(action['id'],str) or len(action['id'])>100:raise ValueError('交互操作目标无效')
        state=action['state']
        if not isinstance(state,dict) or not state or set(state)-{'activeTab','query','sort','page','viewport','hiddenSeries','focus'}:raise ValueError('交互状态无效')
        if 'focus' in state and type(state['focus']) is not bool:raise ValueError('交互 focus 需要布尔值')
        if 'activeTab' in state and not isinstance(state['activeTab'],str):raise ValueError('页签 ID 无效')
        if 'query' in state and (not isinstance(state['query'],str) or len(state['query'])>200):raise ValueError('检索文字过长')
        if 'page' in state and (type(state['page']) is not int or not 0<=state['page']<=20000):raise ValueError('表格页码无效')
        if 'sort' in state:
            sort=state['sort']
            if not isinstance(sort,dict) or set(sort)!={'column','direction'} or not isinstance(sort['column'],str) or len(sort['column'])>300 or sort['direction'] not in {'asc','desc'}:raise ValueError('排序状态无效')
        if 'viewport' in state and state['viewport'] is not None:
            viewport=state['viewport']
            if not isinstance(viewport,dict) or not viewport or set(viewport)-{'x','y'}:raise ValueError('图表范围无效')
            for pair in viewport.values():
                if not isinstance(pair,list) or len(pair)!=2 or not all(not isinstance(v,bool) and isinstance(v,(float,int)) and math.isfinite(v) for v in pair) or pair[0]>=pair[1]:raise ValueError('图表范围需为有限的递增数对')
        if 'hiddenSeries' in state and (not isinstance(state['hiddenSeries'],list) or len(state['hiddenSeries'])>12 or any(type(i) is not int or not 0<=i<12 for i in state['hiddenSeries'])):raise ValueError('图例序号无效')
        if nodes is None:continue
        node=nodes.get(action['id'])
        if not node:raise ValueError('交互操作引用不存在的组件：'+action['id'])
        kind=node['type']
        if 'activeTab' in state and (kind!='tabs' or not any(c['id']==state['activeTab'] for c in node['children'])):raise ValueError('目标不是该页签容器的子页签')
        if set(state)&{'query','sort','page'} and kind!='table':raise ValueError('检索/排序/分页仅作用于表格')
        if set(state)&{'viewport','hiddenSeries'} and kind not in CHARTS:raise ValueError('缩放/图例仅作用于图表')
        if 'hiddenSeries' in state and any(i>=len(node.get('series',[{}])) for i in state['hiddenSeries']):raise ValueError('图例序号超过实际序列数量')
