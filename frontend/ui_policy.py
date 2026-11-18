"""Host presentation policy: no scalar cards or duplicate result windows."""
import copy
import hashlib
import json
import re

SCALAR_TEXT=re.compile(r'^\s*[+\-−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?\s*(?:[A-Za-zµμ°℃%][A-Za-z0-9µμ°℃%/·^²³* ._-]{0,24})?\s*$')


def content_key(node):
    # IDs in sources/columns are data identities; only component identity is ignored.
    value={k:v for k,v in node.items() if k not in {'id','title'}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]


def clean_document(document):
    if not document:return None,[]
    document=copy.deepcopy(document);seen=set();removed=[]
    # Keep the citation at the conclusion. Alternate tabs and conditional
    # panels still need their own evidence when the other panel is hidden.
    inline=set();used=set()
    def scopes(node,scope):
        for child in node.get('children',[]):
            local=scope+(child['id'],) if node['type']=='tabs' or 'visible' in child else scope
            yield child,local
    def collect_inline(node,scope):
        if node['type']=='metric' or node['type']=='text' and SCALAR_TEXT.fullmatch(node.get('text','')):return
        inline.update((scope,k) for k in node.get('evidence',[]))
        for child,local in scopes(node,scope):collect_inline(child,local)
    for slot in ('root','aside'):
        if document.get(slot):collect_inline(document[slot],(document[slot]['id'],) if 'visible' in document[slot] else ())
    def visit(node,scope=()):
        if node['type']=='metric' or node['type']=='text' and SCALAR_TEXT.fullmatch(node.get('text','')):removed.append(node['id']);return None
        original_key=content_key(node) if 'children' not in node and node['type'] not in {'controls','button'} else None
        if original_key and (scope,original_key) in seen:
            removed.append(node['id']);return None
        for key in ('evidence','claims'):
            if key not in node:continue
            keep=[]
            for claim in node[key]:
                ref=(scope,claim)
                if ref in used or key=='claims' and ref in inline:continue
                keep.append(claim);used.add(ref)
            if keep:node[key]=keep
            else:node.pop(key)
            if key=='claims' and not keep:removed.append(node['id']);return None
        if 'children' in node:
            node['children']=[value for child,local in scopes(node,scope) if (value:=visit(child,local))]
            if not node['children']:removed.append(node['id']);return None
        elif original_key:seen.add((scope,original_key))
        return node
    def visit_slot(node):return visit(node,(node['id'],) if 'visible' in node else ()) if node else None
    root=visit_slot(document['root']);aside=visit_slot(document.get('aside'))
    if root is None:
        # Keep the native renderer available when a generated pane became empty.
        if aside:
            ids=set()
            def collect(n):
                ids.add(n['id'])
                for c in n.get('children',[]):collect(c)
            collect(aside);ident='retainedModel'
            while ident in ids:ident+='Host'
            root={'id':ident,'type':'model'}
        else:return None,removed
    document['root']=root
    if aside:document['aside']=aside
    else:document.pop('aside',None)
    return document,removed
