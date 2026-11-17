"""Data-only scientific chart/table presentation primitives."""
import math
import re

CHARTS={'chart','lineChart','scatterChart','barChart','intervalChart','heatmapChart'}
COMMON={'xLabel','yLabel','xAxis','yAxis','height','legend','references','caption'}
SERIES_KEYS={'label','source','x','y','color','mark','dash','marker','width','size','opacity','step','order','xLow','xHigh','yLow','yHigh'}
MARKS={'line','scatter','bar','interval'}
MARKERS={'none','circle','square','triangle','diamond'}


def fail(message):raise ValueError('展示图表：'+message)
def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def text(v):
    if not isinstance(v,str) or len(v)>500:fail('文字或列名无效')
def color(v):
    if not isinstance(v,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v):fail('颜色须为 #RRGGBB')
def limits(v,low,high):
    if not number(v) or not low<=v<=high:fail('尺寸或透明度超出范围')


def validate_chart(node,validate_source):
    for key in ['xLabel','yLabel','caption']:
        if key in node:text(node[key])
    if 'height' in node:limits(node['height'],220,800)
    if node.get('legend','bottom') not in {'bottom','right','none'}:fail('图例位置无效')
    for name in ['xAxis','yAxis']:
        axis=node.get(name,{})
        if not isinstance(axis,dict) or set(axis)-{'label','scale','min','max','reverse','grid','ticks'}:fail('坐标轴配置无效')
        if axis.get('scale','linear') not in {'linear','log'}:fail('仅支持线性或对数轴')
        if 'label' in axis:text(axis['label'])
        if 'ticks' in axis and (not isinstance(axis['ticks'],list) or not 1<=len(axis['ticks'])<=30 or not all(number(v) and (axis.get('scale')!='log' or v>0) for v in axis['ticks'])):fail('坐标刻度无效')
        for key in ['min','max']:
            if key in axis and (not number(axis[key]) or axis.get('scale')=='log' and axis[key]<=0):fail('对数轴要求正数，边界须为有限数值')
        if 'min' in axis and 'max' in axis and axis['min']>=axis['max']:fail('坐标轴下限须小于上限')
        for key in ['reverse','grid']:
            if key in axis and not isinstance(axis[key],bool):fail('坐标轴开关无效')
    references=node.get('references',[])
    if not isinstance(references,list) or len(references)>20:fail('参考线或容差带数量无效')
    for ref in references:
        if not isinstance(ref,dict) or set(ref)-{'axis','value','from','to','label','color','dash','opacity'} or ref.get('axis') not in {'x','y'}:fail('参考线或容差带无效')
        if 'value' in ref:
            if 'from' in ref or 'to' in ref or not number(ref['value']):fail('参考线需要有限数值')
        elif not (number(ref.get('from')) and number(ref.get('to')) and ref['from']<ref['to']):fail('容差带需要下限 < 上限')
        if 'label' in ref:text(ref['label'])
        if 'color' in ref:color(ref['color'])
        if ref.get('dash','dash') not in {'solid','dash','dot'}:fail('参考线线型无效')
        if 'opacity' in ref:limits(ref['opacity'],.02,1)
    if node['type']=='heatmapChart':
        validate_source(node.get('source'))
        for key in ['x','y','value']:text(node.get(key))
        if 'palette' in node:
            from rendering import palette
            palette(node['palette'])
        if 'colorRange' in node:
            v=node['colorRange']
            if not isinstance(v,list) or len(v)!=2 or not all(number(x) for x in v) or v[0]>=v[1]:fail('色标下限须小于上限')
        if 'valueDigits' in node and (type(node['valueDigits']) is not int or not 0<=node['valueDigits']<=8):fail('热图小数位无效')
        if 'showValues' in node and not isinstance(node['showValues'],bool):fail('热图数值开关无效')
        return
    series=node.get('series')
    if not isinstance(series,list) or not 1<=len(series)<=12:fail('图表需要 1–12 条真实数据序列')
    for entry in series:
        if not isinstance(entry,dict) or set(entry)-SERIES_KEYS:fail('图表序列属性无效')
        text(entry.get('label'));validate_source(entry.get('source'))
        for key in ['x','y','xLow','xHigh','yLow','yHigh']:
            if key in entry:text(entry[key])
        if entry.get('mark','line') not in MARKS or entry.get('marker','none') not in MARKERS or entry.get('dash','solid') not in {'solid','dash','dot'}:fail('图元、点形或线型无效')
        if 'color' in entry:color(entry['color'])
        for key,low,high in [('width',.5,6),('size',1,12),('opacity',.02,1)]:
            if key in entry:limits(entry[key],low,high)
        if 'step' in entry and not isinstance(entry['step'],bool):fail('阶梯线开关无效')
        if entry.get('order','source') not in {'source','x'}:fail('连线顺序无效')
        for low,high in [('xLow','xHigh'),('yLow','yHigh')]:
            if (low in entry)!=(high in entry):fail('区间端点列需成对提供')
        if (entry.get('mark')=='interval' or node['type']=='intervalChart') and not any(k in entry for k in ['xLow','yLow']):fail('区间图需要真实上下界列')


def validate_table(node):
    columns=node.get('columns')
    if columns is not None:
        if not isinstance(columns,list) or not 1<=len(columns)<=32:fail('表格列数无效')
        ids=[]
        for column in columns:
            if isinstance(column,str):text(column);ids.append(column);continue
            if not isinstance(column,dict) or set(column)-{'id','label','unit','format','digits','align'}:fail('表格列配置无效')
            for key in ['id','label','unit']:
                if key in column:text(column[key])
            if 'id' not in column:fail('表格列需要 ID')
            ids.append(column['id'])
            if column.get('format','auto') not in {'auto','fixed','scientific'} or column.get('align','right') not in {'left','center','right'}:fail('表格格式无效')
            if 'digits' in column and (type(column['digits']) is not int or not 0<=column['digits']<=12):fail('表格小数位无效')
        if len(set(ids))!=len(ids):fail('表格不能重复列')
    if 'pageSize' in node and (type(node['pageSize']) is not int or not 10<=node['pageSize']<=200):fail('表格分页范围无效')
    if 'searchable' in node and not isinstance(node['searchable'],bool):fail('表格搜索开关无效')
    if 'sort' in node:
        sort=node['sort']
        if not isinstance(sort,dict) or set(sort)!={'column','direction'} or sort['direction'] not in {'asc','desc'}:fail('表格排序无效')
        text(sort['column'])
    if 'highlight' in node:
        rule=node['highlight']
        if not isinstance(rule,dict) or set(rule)!={'column','mode'} or rule['mode'] not in {'min','max'}:fail('表格突出显示配置无效')
        text(rule['column'])
