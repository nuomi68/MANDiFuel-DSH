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
    def visit(node):
        if node['type']=='metric' or node['type']=='text' and SCALAR_TEXT.fullmatch(node.get('text','')):removed.append(node['id']);return None
        if 'children' in node:
            node['children']=[child for child in (visit(c) for c in node['children']) if child]
            if not node['children']:removed.append(node['id']);return None
        elif node['type'] not in {'controls','button'}:
            key=content_key(node)
            if key in seen:removed.append(node['id']);return None
            seen.add(key)
        return node
    root=visit(document['root']);aside=visit(document['aside']) if document.get('aside') else None
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
