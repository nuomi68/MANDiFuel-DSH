"""Revisioned, data-only operations on the agent-owned frontend slots."""
import copy
import hashlib
import json

SLOTS={
    'main':{'content':'component tree','location':'left content area'},
    'aside':{'content':'component tree','location':'below native DSH'},
    'settings':{'content':'parameter definitions','location':'display settings drawer'},
    'model':{'content':'rendering and view state','location':'reserved renderer; use update'},
}


def frontend_revision(meta):
    state={k:meta.get(k) for k in ('presentationVersion','workspaceRevision','promptRevision','displayPromptRevision','defaultView','modelVersion')}
    state['workspaceWatch']=meta.get('workspaceWatch',{}).get('revision')
    state['parameters']=meta.get('presentation',{}).get('parameterValues',{})
    state['evidence']=meta.get('evidence',{}).get('revision')
    state['viewer']=meta.get('viewerState',{})
    state['browserParameters']=meta.get('uiState',{}).get('parameters',{})
    state['pickedPoint']=meta.get('uiState',{}).get('pickedPoint')
    state['browserDisplay']=meta.get('uiState',{}).get('display',{})
    observation=meta.get('uiState',{})
    state['browserSelection']={k:v for k,v in observation.get('selection',{}).items() if k!='settingsOpen'}
    state['browserInteractions']=sorted([{'id':n['id'],**{k:n[k] for k in ('activeTab','table','chart') if k in n}} for n in observation.get('nodes',[]) if any(k in n for k in ('activeTab','table','chart'))],key=lambda n:n['id'])
    return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]


class FrontendConflict(ValueError):
    pass


def _find(node,ident,parent=None):
    if not isinstance(node,dict):return None
    if node.get('id')==ident:return node,parent
    for child in node.get('children',[]):
        found=_find(child,ident,node)
        if found:return found
    return None


def patch_slots(presentation,request):
    if not isinstance(request,dict) or set(request)-{'expectedRevision','expectedRequest','operations','datasets','update'}:raise ValueError('插槽请求属性无效')
    operations=request.get('operations',[]);update=copy.deepcopy(request.get('update',{}))
    if not isinstance(operations,list) or len(operations)>24 or not isinstance(update,dict):raise ValueError('插槽操作数量或更新类型无效')
    datasets=request.get('datasets',{})
    if not isinstance(datasets,dict):raise ValueError('datasets 需要数据表 ID 到来源的映射')
    if datasets and 'ui' in update:raise ValueError('完整页面的数据源放在 update.ui.datasets')
    if not operations and not update and not datasets:raise ValueError('插槽更新为空')
    ui=copy.deepcopy(presentation.get('ui'));tree_changed=False;interactions=[]
    controls=copy.deepcopy(presentation.get('controls',[]));changed=set()
    for operation in operations:
        if not isinstance(operation,dict):raise ValueError('插槽操作必须是对象')
        op=operation.get('op');slot=operation.get('slot')
        if not isinstance(op,str) or not isinstance(slot,str):raise ValueError('插槽与操作名称必须是字符串')
        if slot not in {'main','aside','settings'}:raise ValueError('插槽不可写：'+str(slot))
        if slot=='settings':
            if 'controls' in update:raise ValueError('不能同时通过 update.controls 和插槽操作修改设置')
            if op=='replace' and set(operation)=={'op','slot','value'} and isinstance(operation['value'],list):controls=copy.deepcopy(operation['value'])
            elif op=='upsert' and set(operation)=={'op','slot','value'} and isinstance(operation['value'],dict):
                value=copy.deepcopy(operation['value']);ident=value.get('id')
                if not isinstance(ident,str):raise ValueError('设置控件需要 ID')
                index=next((i for i,c in enumerate(controls) if c.get('id')==ident),None)
                if index is None:controls.append(value)
                else:controls[index]={**controls[index],**value}
            elif op=='remove' and set(operation)=={'op','slot','id'}:
                if not any(c.get('id')==operation['id'] for c in controls):raise ValueError('设置控件不存在')
                controls=[c for c in controls if c.get('id')!=operation['id']]
            else:raise ValueError('设置插槽支持 replace/upsert/remove；upsert 格式为 {op,slot,value:{id,...定义}}，外层不要 id；只改当前参数值用 update.parameterValues')
            changed.add(slot);continue
        if 'ui' in update:raise ValueError('不能同时通过 update.ui 和插槽操作修改组件树')
        if ui is None:ui={'version':1,'mode':'above','root':{'id':'mainModel','type':'model'}}
        key='root' if slot=='main' else 'aside';tree=ui.get(key)
        if op=='interact':
            if set(operation)!={'op','slot','id','state'} or not _find(tree,operation['id']):raise ValueError('交互操作目标不存在或属性无效')
            interactions.append({'id':operation['id'],'state':copy.deepcopy(operation['state'])});changed.add(slot);continue
        tree_changed=True
        if op=='replace':
            if set(operation)-{'op','slot','id','value'} or 'value' not in operation:raise ValueError('replace 操作属性无效')
            value=copy.deepcopy(operation['value'])
            if 'id' not in operation:
                if value is None and slot=='aside':ui.pop(key,None)
                elif not isinstance(value,dict):raise ValueError('主区或侧区需要组件树')
                else:ui[key]=value
            else:
                found=_find(tree,operation['id'])
                if not found or not isinstance(value,dict):raise ValueError('待替换组件不存在或类型无效')
                node,parent=found
                if parent:parent['children'][parent['children'].index(node)]=value
                else:ui[key]=value
        elif op=='update':
            if set(operation)!={'op','slot','id','props'} or not isinstance(operation['props'],dict) or {'id','type'}&operation['props'].keys():raise ValueError('组件 update 不可改变 ID 或类型；请使用 replace')
            found=_find(tree,operation['id'])
            if not found:raise ValueError('组件不存在：'+str(operation['id']))
            found[0].update(copy.deepcopy(operation['props']))
        elif op=='insert':
            if set(operation)-{'op','slot','parent','index','value'} or not {'parent','value'}<=operation.keys():raise ValueError('insert 操作属性无效')
            _insert(tree,operation['parent'],operation.get('index'),copy.deepcopy(operation['value']))
        elif op in {'remove','move'}:
            allowed={'op','slot','id'} if op=='remove' else {'op','slot','id','toSlot','parent','index'}
            if set(operation)-allowed or 'id' not in operation:raise ValueError('移除或移动操作属性无效')
            found=_find(tree,operation['id'])
            if not found:raise ValueError('组件不存在：'+str(operation['id']))
            node,parent=found
            if not parent:
                if op=='remove' and slot=='aside':ui.pop(key,None);changed.add(slot);continue
                raise ValueError('根组件请通过插槽 replace 操作替换')
            if op=='move':
                target=operation.get('toSlot',slot)
                if target not in {'main','aside'}:raise ValueError('组件只能在主区与侧区之间移动')
                if _find(node,operation.get('parent')):raise ValueError('不能把组件移动到自身或其子组件中')
                parent['children'].remove(node)
                _insert(ui.get('root' if target=='main' else 'aside'),operation.get('parent'),operation.get('index'),node)
                changed.add(target)
            else:parent['children'].remove(node)
        else:raise ValueError('未知插槽操作：'+str(op))
        changed.add(slot)
    if datasets:
        if ui is None:ui={'version':1,'mode':'above','root':{'id':'mainModel','type':'model'}}
        ui.setdefault('datasets',{}).update(datasets)
        tree_changed=True
    if tree_changed:update['ui']=ui
    if interactions:
        if 'interactions' in update:raise ValueError('交互操作不能重复定义')
        update['interactions']=interactions
    if 'settings' in changed:update['controls']=controls
    return update,sorted(changed)


def _insert(tree,parent_id,index,value):
    found=_find(tree,parent_id)
    if not found or found[0].get('type') not in {'row','column','grid','tabs'}:raise ValueError('目标父组件不存在或不是布局容器')
    if not isinstance(value,dict):raise ValueError('插入内容必须是组件')
    children=found[0]['children'];index=len(children) if index is None else index
    if type(index) is not int or not 0<=index<=len(children):raise ValueError('插入位置超出范围')
    children.insert(index,value)
