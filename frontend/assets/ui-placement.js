// Generated controls belong to Display Settings unless inline placement is explicit.
export function uiInScope(document,context){
 if(!document)return false;
 return !context?.hasStudy||(document.scope||'all')==='all'||document.scope===context.state?.panel;
}
export function hasWorkspaceContent(node){
 if(node.type==='controls')return node.placement==='inline';
 return node.children?node.children.some(hasWorkspaceContent):true;
}

// Case-specific tabs can sit beside a comparison or notes in the same tab list.
export function caseTabs(children){
 const targets=new Map();
 function sources(node){
  if(node.children)return node.children.flatMap(sources);
  if(node.series)return node.series.map(series=>series.source);
  return node.source?[node.source]:[];
 }
 for(const child of children){
  const bound=sources(child).map(source=>source?.view||(!source?.selection?.viewColumn&&source?.selection?.view));
  if(!bound.length||bound.some(view=>!view)||new Set(bound).size!==1)continue;
  targets.set(child.id,bound[0]);
 }
 return targets.size>1&&new Set(targets.values()).size===targets.size?targets:null;
}

export function settingsControlGroups(document,isVisible=()=>true){
 const groups=[];
 function visit(node){
  if(!isVisible(node))return;
  if(node.type==='controls'&&node.placement!=='inline')groups.push({title:node.title||'',ids:node.ids});
  for(const child of node.children||[])visit(child);
 }
 if(document){visit(document.root);if(document.aside)visit(document.aside);}
 return groups;
}

export function groupSettingsControls(controls,groups,document){
 const referenced=new Set(),visible=new Set(groups.flatMap(g=>g.ids));
 function visit(node){if(node.type==='controls')for(const id of node.ids)referenced.add(id);for(const child of node.children||[])visit(child);}
 if(document){visit(document.root);if(document.aside)visit(document.aside);}
 const remaining=new Map(controls.filter(c=>!referenced.has(c.id)||visible.has(c.id)).map(c=>[c.id,c])),result=[];
 for(const group of groups)for(const id of group.ids){const c=remaining.get(id);if(c){result.push({...c,group:group.title||c.group});remaining.delete(id);}}
 return [...remaining.values(),...result];
}
