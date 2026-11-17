"""Typed rendering instructions shared by the presenter and the workbench."""
import copy
import math
import re
from agent_panel import validate_program,LANGUAGE

PALETTES={'coolwarm','viridis','inferno','gray','rainbow'}
DEFAULTS={'scale':[1,1,1],'showScaleControls':False,'palette':'coolwarm','reversePalette':False,'opacity':1,'background':'#f1f5fc','wireColor':'#3d6eb3','fields':{},'program':None}
CAPABILITIES={'scale':{'axes':['x','y','z'],'min':.01,'max':100,'displayOnly':True},'palettes':sorted(PALETTES),'customPalette':{'colors':'#RRGGBB','maxStops':16},'opacity':{'min':.05,'max':1,'kind':'surface'},'colors':['background','wireColor'],'perField':['palette','reversePalette','range'],'incrementalUpdates':True,'reset':True,'unsupported':['volumeRendering','isosurface','fieldDrivenDeformation']}
CAPABILITIES['parameterPanel']={'agentDefinedIds':True,'types':['number','range','toggle','select','color','text'],'groups':True,'units':True,'help':True,'bindings':LANGUAGE}


def finite(value):return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)
def color(value):return isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)


def show_scale_controls(rendering=None):
    rendering=rendering or {}
    return rendering.get('showScaleControls') is True or any(v!=1 for v in rendering.get('scale',[1,1,1]))


def palette(value):
    if isinstance(value,str):
        if value not in PALETTES:raise ValueError('未知色带；可使用命名色带或自定义 [位置, #RRGGBB] 色阶')
    elif isinstance(value,list) and 2<=len(value)<=16:
        previous=-1
        for row in value:
            if not isinstance(row,list) or len(row)!=2 or not finite(row[0]) or not previous<row[0]<=1 or not color(row[1]):raise ValueError('自定义色阶须按 0–1 递增且使用 #RRGGBB 颜色')
            previous=row[0]
        if value[0][0]!=0 or value[-1][0]!=1:raise ValueError('自定义色阶必须覆盖 0 和 1')
    else:raise ValueError('色带配置无效')
    return copy.deepcopy(value)


def validate_rendering(update):
    if not isinstance(update,dict) or set(update)-set(DEFAULTS)-{'reset'}:raise ValueError('不支持的渲染配置；请根据实际渲染能力调整')
    result={}
    for key,value in update.items():
        if key=='reset':
            if not isinstance(value,bool):raise ValueError('重置开关无效')
        elif key=='scale':
            if not isinstance(value,list) or len(value)!=3 or not all(finite(v) and .01<=v<=100 for v in value):raise ValueError('XYZ 显示缩放须为三个 0.01–100 的正数')
        elif key=='program':value=validate_program(value)
        elif key=='palette':value=palette(value)
        elif key in {'reversePalette','showScaleControls'}:
            if not isinstance(value,bool):raise ValueError('色带反转开关无效')
        elif key=='opacity':
            if not finite(value) or not .05<=value<=1:raise ValueError('表面透明度须为 0.05–1')
        elif key in {'background','wireColor'}:
            if not color(value):raise ValueError('颜色须为 #RRGGBB')
        elif key=='fields':
            if not isinstance(value,dict) or len(value)>100:raise ValueError('字段渲染配置无效')
            for ident,style in value.items():
                if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',ident) or not isinstance(style,dict) or set(style)-{'palette','reversePalette','range'}:raise ValueError('字段渲染配置无效')
                if 'palette' in style:palette(style['palette'])
                if 'reversePalette' in style and not isinstance(style['reversePalette'],bool):raise ValueError('字段色带反转开关无效')
                if 'range' in style and style['range'] is not None:
                    limits=style['range']
                    if not isinstance(limits,list) or len(limits)!=2 or not all(finite(v) for v in limits) or limits[0]>=limits[1]:raise ValueError('自定义色标需要有限的最小值 < 最大值，单位沿用该字段')
        result[key]=copy.deepcopy(value)
    return result


def merge_rendering(previous,update):
    result=copy.deepcopy(DEFAULTS if update.get('reset') else previous or {})
    for key,value in update.items():
        if key=='reset':continue
        if key=='fields':
            fields=result.setdefault('fields',{})
            for ident,style in value.items():fields[ident]={**fields.get(ident,{}),**style}
        else:result[key]=copy.deepcopy(value)
    return result
