import {renderParameterPanel} from './parameter-panel.js';
import {compileExpression} from './render-program.js';
import {resolveSource} from './data-sources.js';
import {chartSVG,CHART_TYPES,escape,format,tableCSV,tableColumns,tableRows,formatCell,chartDataTable} from './chart-view.js';
import {hasWorkspaceContent,settingsControlGroups,uiInScope,caseTabs} from './ui-placement.js';
import {ChartInteraction} from './chart-interaction.js';
import {evidenceLink,evidenceLabels} from './evidence-browser.js';

const containers=new Set(['row','column','grid','tabs']);
const element=(tag,className,text)=>{const e=document.createElement(tag);if(className)e.className=className;if(text!==undefined)e.textContent=text;return e;};
function download(blob,name){const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function svgImage(svg){const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml;charset=utf-8'}));try{const image=new Image();image.src=url;await image.decode();return image;}finally{URL.revokeObjectURL(url);}}
async function paintSVG(context,svg,x,y,width,height){
 await document.fonts.ready;
 const clone=svg.cloneNode(true);for(const text of clone.querySelectorAll('text'))text.remove();
 context.drawImage(await svgImage(new XMLSerializer().serializeToString(clone)),x,y,width,height);
 const box=svg.getBoundingClientRect();
 for(const text of svg.querySelectorAll('text')){
  const matrix=text.getScreenCTM(),style=getComputedStyle(text);if(!matrix)continue;
  context.save();context.translate(x,y);context.scale(width/box.width,height/box.height);context.transform(matrix.a,matrix.b,matrix.c,matrix.d,matrix.e-box.x,matrix.f-box.y);
  context.fillStyle=style.fill;context.font=`${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;context.textAlign=style.textAnchor==='middle'?'center':style.textAnchor==='end'?'right':'left';context.fillText(text.textContent,Number(text.getAttribute('x')||0),Number(text.getAttribute('y')||0));context.restore();
 }
}

export class AdaptiveUI{
 constructor({host,aside,model,onAction,onRun,onControlInput,onControlChange,onObserve,onRendered,getModelImage}){
  Object.assign(this,{host,aside,model,onAction,onRun,onControlInput,onControlChange,onObserve,onRendered,getModelImage});
  this.asideAnchor=document.createComment('supplemental analysis location');aside.before(this.asideAnchor);window.addEventListener('workbench-layout',()=>this.syncAsidePlacement());
  this.anchor=document.createComment('original model location');model.before(this.anchor);this.nodes=new Map();this.key=null;this.dataKey=null;this.generation=0;this.context=null;this.document=null;this.datasetCache=new Map();this.lastObservation=null;this.ready=false;
  this.resizeObserver=new ResizeObserver(items=>{for(const item of items){const entry=this.nodes.get(item.target.dataset.uiBody);if(entry?.body===item.target&&entry.series&&entry.chartWidth!==Math.round(entry.body.clientWidth))try{this.paintChart(entry,entry.series);}catch(error){this.showError(entry,error);}}});
  document.addEventListener('fullscreenchange',()=>{for(const entry of this.nodes.values())if(entry.series)this.paintChart(entry,entry.series);});
 }
 get inScope(){return uiInScope(this.document,this.context);}
 get active(){return this.inScope&&hasWorkspaceContent(this.document.root);}
 get replaces(){return this.inScope&&this.document?.mode==='replace'&&hasWorkspaceContent(this.document.root);}
 get settingsGroups(){if(!this.inScope)return[];return settingsControlGroups(this.document,node=>this.nodes.get(node.id)?.visibleValue!==false);}
 restoreModel(){if(this.anchor.nextSibling!==this.model)this.anchor.after(this.model);}
 update(document,context){
  const sameTask=this.context?.taskId===context.taskId,previousView=this.context?.state.view;
  this.context=context;const key=JSON.stringify([context.taskId,context.uiRevision,document||null]);
  if(key!==this.key){
   this.previousStates=new Map(sameTask?[...this.nodes].map(([id,e])=>[id,{type:e.node.type,modelDirective:e.modelDirective,page:e.page,query:e.query,sort:e.sort,declaredSort:JSON.stringify(e.node.sort),activeTab:e.activeTab,dataIdentity:e.dataIdentity,viewport:e.interaction?.viewport,hidden:e.interaction?[...e.interaction.hidden]:[]}]):[]);
   this.key=key;this.dataKey=null;this.generation++;this.resizeObserver.disconnect();this.restoreModel();this.nodes.clear();this.host.replaceChildren();this.aside.replaceChildren();this.document=document;this.host.hidden=!document||!hasWorkspaceContent(document.root);this.modelSlot=null;this.ready=false;
   if(!document){this.syncVisibility();return;}
   if(document.mode==='below')this.model.after(this.host);else this.anchor.before(this.host);
   this.selectionBar=element('aside','adaptive-selection');this.selectionBar.hidden=true;this.selectionBar.setAttribute('aria-live','polite');this.host.append(this.selectionBar);
   const root=this.build(document.root);if(hasWorkspaceContent(document.root))this.host.append(root);
   if(document.aside)this.aside.append(this.build(document.aside));
   if(this.modelSlot)this.modelSlot.append(this.model);
   this.previousStates=null;
  }
  this.syncVisibility();if(!document)return;this.syncSelection();
  for(const entry of this.nodes.values()){
   if(entry.node.type==='evidence')this.renderEvidence(entry);
   if(entry.node.evidence?.length)this.renderEvidence(entry,true);
   if(entry.node.type==='controls'&&entry.node.placement==='inline')this.renderControls(entry);
   if(entry.visible){try{const visible=entry.visible(context.bounds||{},context.parameters);if(typeof visible!=='boolean')throw new Error('组件可见性需要布尔值');entry.visibleValue=visible;entry.element.hidden=!visible;entry.visibilityError=null;}catch(error){entry.visibilityError=error.message;entry.element.hidden=false;}}
  }
  for(const entry of this.nodes.values())if(entry.selectTab){
   const visible=entry.node.children.filter(n=>hasWorkspaceContent(n)&&this.nodes.get(n.id)?.visibleValue!==false);
   const followView=entry.caseTabs&&(previousView!==context.state.view||entry.caseTabs.has(entry.activeTab));
   const matching=followView&&context.state.view&&visible.find(n=>entry.caseTabs.get(n.id)===context.state.view);
   if(matching)entry.selectTab(matching.id);
   else if(visible.length)entry.selectTab(visible.some(n=>n.id===entry.activeTab)?entry.activeTab:visible[0].id);
  }
  const dataKey=JSON.stringify([context.dataKey,context.parameters]);if(dataKey!==this.dataKey){this.dataKey=dataKey;void this.renderData();}
  this.applyInteractions();this.syncVisibility();
 }
 applyInteractions(){
  const key=JSON.stringify([this.context.taskId,this.context.interactionRevision||0]);if(key===this.interactionKey)return;this.interactionKey=key;
  for(const action of this.context.interactions||[]){const entry=this.nodes.get(action.id);if(!entry)continue;const s=action.state;
   try{
    if(s.activeTab!==undefined)entry.activateTab(s.activeTab);
    if(entry.node.type==='table'){
     if(s.query!==undefined){entry.query=s.query;entry.page=0;const input=entry.element.querySelector('input[type=search]');if(input)input.value=s.query;}
     if(s.sort!==undefined){entry.sort=s.sort;entry.page=0;}if(s.page!==undefined)entry.page=s.page;
     if(entry.table)this.renderTable(entry);
    }
    if(entry.interaction){if(Object.hasOwn(s,'viewport'))entry.interaction.viewport=s.viewport;if(s.hiddenSeries!==undefined)entry.interaction.hidden=new Set(s.hiddenSeries);if(entry.series)entry.interaction.repaint();}
    if(s.focus)entry.element.scrollIntoView({block:'nearest'});
   }catch(error){this.showError(entry,error);}
  }
  this.observe();
 }
 syncAsidePlacement(){const anchor=document.getElementById('workspace-body').classList.contains('chat-open')?this.asideAnchor:this.host;if(anchor.nextSibling!==this.aside)anchor.after(this.aside);}
 syncVisibility(){
  this.host.hidden=!this.active;this.aside.hidden=!this.inScope||!this.document?.aside||!hasWorkspaceContent(this.document.aside);this.syncAsidePlacement();
  const slotVisible=this.modelSlot&&this.inScope&&!this.modelSlot.closest('[hidden]');
  if(slotVisible){if(this.model.parentNode!==this.modelSlot)this.modelSlot.append(this.model);}
  else{this.restoreModel();if(this.active&&this.model.nextSibling!==this.host)this.model.after(this.host);}
  this.model.hidden=!!this.context?.modelHidden;
 }
 build(node){
  const wrapper=element('section',containers.has(node.type)?'adaptive-layout adaptive-'+(node.type==='tabs'?'tab-layout':node.type):node.type==='button'?'adaptive-button':'adaptive-card');wrapper.dataset.uiNode=node.id;wrapper.dataset.uiType=node.type;
  const previous=this.previousStates?.get(node.id),retained=previous?.type===node.type?previous:null;
  const dataIdentity=JSON.stringify([node.source,node.series?.map(s=>({source:s.source,x:s.x,y:s.y,xLow:s.xLow,xHigh:s.xHigh,yLow:s.yLow,yHigh:s.yHigh})),this.document?.datasets]);
  const entry={node,element:wrapper,visible:Object.hasOwn(node,'visible')?compileExpression(node.visible):null,page:retained?.page||0,query:retained?.query||'',sort:retained&&retained.declaredSort===JSON.stringify(node.sort)?retained.sort:node.sort||null,error:null,visibilityError:null,dataIdentity};this.nodes.set(node.id,entry);
  if(node.title&&node.type!=='model')wrapper.append(element('h2','adaptive-title',node.title));
  if(containers.has(node.type)){
   if(node.type==='grid'){wrapper.dataset.columns=String(node.columns||2);wrapper.dataset.chartGrid=String(node.children.some(n=>CHART_TYPES.has(n.type)));wrapper.dataset.metricGrid=String(node.children.every(n=>n.type==='metric'));}
   if(node.type==='tabs'){
    const nav=element('div','adaptive-tabs');nav.setAttribute('role','tablist');const content=element('div','adaptive-tab-content');wrapper.append(nav,content);let current=node.children.some(c=>c.id===retained?.activeTab)?retained.activeTab:node.children[0].id;
    const select=id=>{current=id;entry.activeTab=id;for(const child of content.children)child.hidden=child.dataset.uiNode!==id||this.nodes.get(child.dataset.uiNode)?.visibleValue===false;for(const button of nav.children){button.hidden=this.nodes.get(button.dataset.target)?.visibleValue===false;button.setAttribute('aria-selected',String(button.dataset.target===id));button.tabIndex=button.dataset.target===id?0:-1;}};entry.selectTab=select;
    entry.caseTabs=caseTabs(node.children);
    entry.activateTab=id=>{
     const view=entry.caseTabs?.get(id);
     if(view&&view!==this.context.state.view)return this.selectLinked({view},entry);
     select(id);
    };
    for(const child of node.children){const panel=this.build(child);if(!hasWorkspaceContent(child))continue;if(containers.has(child.type))panel.querySelector(':scope>.adaptive-title')?.remove();const b=element('button','',child.title||child.id);b.type='button';b.id='adaptive-tab-'+child.id;b.dataset.target=child.id;b.setAttribute('role','tab');b.setAttribute('aria-controls','adaptive-panel-'+child.id);if(entry.caseTabs?.has(child.id))b.dataset.selectView=entry.caseTabs.get(child.id);b.addEventListener('click',()=>entry.activateTab(child.id));b.addEventListener('keydown',event=>{if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...nav.children].filter(x=>!x.hidden),index=buttons.indexOf(b),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:buttons.length-1))%buttons.length;entry.activateTab(buttons[next].dataset.target);buttons[next].focus();});nav.append(b);panel.id='adaptive-panel-'+child.id;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',b.id);content.append(panel);}select(current);
   }else for(const child of node.children){const panel=this.build(child);if(hasWorkspaceContent(child))wrapper.append(panel);}
   return wrapper;
  }
  entry.body=element('div','adaptive-body');entry.body.dataset.uiBody=node.id;wrapper.append(entry.body);
  if(CHART_TYPES.has(node.type))this.resizeObserver.observe(entry.body);
  if(CHART_TYPES.has(node.type)){
   entry.interaction=new ChartInteraction(entry,{paint:()=>this.paintChart(entry,entry.series),select:(id,openModel,selection)=>selection?this.selectLinked(selection,entry):this.selectRun(id,openModel),getStudy:()=>this.context?.study});
   if(retained?.dataIdentity===dataIdentity){entry.interaction.viewport=retained.viewport||null;entry.interaction.hidden=new Set(retained.hidden||[]);}
   const header=element('div','adaptive-chart-heading'),title=wrapper.querySelector('.adaptive-title');if(title)header.append(title);entry.tools=entry.interaction.toolbar();header.append(entry.tools);wrapper.prepend(header);
  }
  if(node.type==='table'&&node.searchable!==false){const toolbar=element('div','adaptive-table-toolbar'),search=element('input');search.type='search';search.value=entry.query;search.placeholder='搜索表格';search.setAttribute('aria-label',(node.title||'数据表')+' · 搜索');search.addEventListener('input',()=>{entry.query=search.value;entry.page=0;this.renderTable(entry);});toolbar.append(search);wrapper.insertBefore(toolbar,entry.body);}
  if(node.type==='table')entry.body.addEventListener('click',event=>{const button=event.target.closest('[data-sort-column]');if(!button)return;const column=button.dataset.sortColumn;entry.sort={column,direction:entry.sort?.column===column&&entry.sort.direction==='asc'?'desc':'asc'};entry.page=0;this.renderTable(entry);});
  if(node.type==='table'){
   entry.body.addEventListener('click',event=>{const row=event.target.closest('tr[data-linked-row]');if(row)this.selectLinked(entry.renderedRows[Number(row.dataset.linkedRow)]?.selection,entry);});
   entry.body.addEventListener('keydown',event=>{const row=event.target.closest('tr[data-linked-row]');if(row&&['Enter',' '].includes(event.key)){event.preventDefault();this.selectLinked(entry.renderedRows[Number(row.dataset.linkedRow)]?.selection,entry);}});
   entry.body.addEventListener('click',event=>{const row=event.target.closest('tr[data-chart-run]');if(row&&!row.dataset.linkedView)this.selectRun(row.dataset.chartRun);});
   entry.body.addEventListener('dblclick',event=>{const row=event.target.closest('tr[data-chart-run]');if(row)this.selectRun(row.dataset.chartRun,true);});
   entry.body.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&event.target.matches('tr[data-chart-run]')){event.preventDefault();this.selectRun(event.target.dataset.chartRun);}});
  }
  if(node.type==='model'){
   wrapper.classList.add('adaptive-model');this.modelSlot=entry.body;
   entry.modelDirective=JSON.stringify(node.state);
   if(node.state&&entry.modelDirective!==retained?.modelDirective)entry.action=Promise.resolve().then(()=>{if(this.nodes.get(node.id)===entry)return this.onAction({type:'view',state:node.state});}).catch(error=>this.showError(entry,error));
  }else if(node.type==='text')entry.body.append(element('p','adaptive-text',node.text));
  else if(node.type==='evidence')this.renderEvidence(entry);
  else if(node.type==='image'){
   const figure=element('figure','adaptive-image'),img=element('img');img.alt=node.alt;img.src=this.context.imageURL(node.file);img.addEventListener('load',()=>{entry.error=null;this.observe();});img.addEventListener('error',()=>this.showError(entry,new Error('图片未能载入')));figure.append(img);if(node.caption)figure.append(element('figcaption','',node.caption));entry.body.append(figure);
  }
  else if(node.type==='button'){
   const button=element('button','adaptive-action',node.label);button.type='button';if(node.action.type==='view'&&node.action.state.view){button.dataset.selectView=node.action.state.view;if(Object.keys(node.action.state).length===1)button.dataset.caseSwitch='true';}button.addEventListener('click',async()=>{button.disabled=true;try{await this.onAction(node.action);entry.error=null;}catch(error){this.showError(entry,error);}finally{button.disabled=false;this.observe();}});entry.body.append(button);
  }else if(node.type==='controls'){
   entry.body.addEventListener('input',e=>this.onControlInput(e));entry.body.addEventListener('change',e=>this.onControlChange(e));
  }else{
   const actions=element('div','adaptive-exports'),csv=element('button','','CSV');csv.type='button';csv.disabled=true;entry.exports=actions;csv.addEventListener('click',()=>{if(entry.table)download(new Blob([tableCSV(entry.table)],{type:'text/csv;charset=utf-8'}),(node.title||node.id)+'.csv');});actions.append(csv);
   if(CHART_TYPES.has(node.type)){const png=element('button','','PNG');png.type='button';png.addEventListener('click',async()=>{try{const svg=entry.body.querySelector('svg');if(!svg)return;const canvas=document.createElement('canvas'),box=svg.getBoundingClientRect();canvas.width=Math.round(box.width*2);canvas.height=Math.round(box.height*2)+70;const c=canvas.getContext('2d');c.fillStyle=this.theme().panel;c.fillRect(0,0,canvas.width,canvas.height);c.fillStyle=this.theme().ink;c.font='24px "Workbench CJK",system-ui';c.fillText(node.title||'分析图',28,38);await paintSVG(c,svg,0,65,canvas.width,canvas.height-70);canvas.toBlob(blob=>{if(blob)download(blob,(node.title||node.id)+'.png');});}catch(error){this.showError(entry,error);}});actions.append(png);const menu=element('details','adaptive-chart-export');menu.append(element('summary','','导出'),actions);entry.tools.append(menu);}else wrapper.append(actions);
  }
  return wrapper;
 }
 renderEvidence(entry,citations=false){
  const ids=citations?entry.node.evidence:entry.node.claims,context=this.context;
  if(citations&&!entry.citations){entry.citations=element('div','adaptive-evidence-citations');entry.element.append(entry.citations);}
  const host=citations?entry.citations:entry.body;host.replaceChildren();
  if(!context?.openEvidence)return;
  const table=citations?host:element('table','adaptive-evidence-table');
  for(const id of ids){
   const claim=context.evidenceClaims?.get(id);
   if(!claim){host.append(element('p','evidence-note','核查记录尚未就绪或已失效，请打开“结果核查”查看当前依据。'));continue;}
   const link=evidenceLink(claim,context.openEvidence);
   if(citations)table.append(link);
   else{const row=element('tr'),name=element('td'),state=element('td');name.append(link);const badge=element('span','evidence-status',evidenceLabels[claim.status]||claim.status);badge.dataset.state=claim.status;state.append(badge);row.append(name,state);table.append(row);}
  }if(!citations)host.append(table);
 }
 theme(){const s=getComputedStyle(this.host),get=(key,fallback)=>s.getPropertyValue(key).trim()||fallback;return{ink:get('--ink','#17171a'),accent:get('--accent','#4f46e5'),line:get('--line','#e5e5e8'),panel:get('--panel','#ffffff')};}
 paintChart(entry,series){
  if(!series)return;entry.series=series;entry.chartWidth=Math.round(entry.body.clientWidth);const node=document.fullscreenElement===entry.element?{...entry.node,height:Math.max(300,window.innerHeight-170)}:entry.node;entry.body.innerHTML=chartSVG(node,series,this.theme(),entry.chartWidth||720,entry.interaction||{});entry.interaction?.afterPaint();this.syncSelection();
 }
 async selectRun(id,openModel=false){if(!this.context?.study?.runs.some(r=>r.id===id))return;try{await this.onRun?.(id,{openModel});this.syncSelection();}catch(error){this.onSelectError=String(error.message||error);}}
 async selectLinked(selection,entry){if(!selection)return;try{await this.onAction({type:'selection',selection});this.syncSelection();}catch(error){this.showError(entry,error);}}
 syncSelection(){
  for(const host of [this.host,this.aside])for(const button of host.querySelectorAll('[data-select-view]:not([role=tab])'))button.setAttribute('aria-pressed',String(button.dataset.selectView===this.context.state.view));
  for(const host of [this.host,this.aside])for(const target of host.querySelectorAll('[data-linked-view]')){const selected=target.dataset.linkedView===this.context.state.view,atTime=target.dataset.linkedTime===undefined||Number(target.dataset.linkedTime)===this.context.time,atPosition=!target.dataset.linkedPosition||target.dataset.linkedPosition===JSON.stringify(this.context.state.pickedPoint?.position);target.dataset.selected=String(selected&&atTime&&atPosition);target.dataset.structureSelected=String(selected);if(target.tagName.toLowerCase()==='tr')target.setAttribute('aria-selected',String(selected&&atTime&&atPosition));}
  const study=this.context?.study,run=study?.runs.find(r=>r.id===this.context.state.run),targets=[...this.host.querySelectorAll('[data-chart-run]'),...this.aside.querySelectorAll('[data-chart-run]')],linked=!!targets.length;
  for(const target of targets){if(target.dataset.linkedView)continue;const selected=target.dataset.chartRun===run?.id;target.dataset.selected=String(selected);if(target.tagName.toLowerCase()==='tr')target.setAttribute('aria-selected',String(selected));else target.setAttribute('aria-pressed',String(selected));}
  if(!this.selectionBar)return;this.selectionBar.hidden=!run||!linked;if(!run||!linked)return;
  const text=element('div'),label=element('strong','',run.label||run.id),values=element('span','',study.responses.map(d=>`${d.label||d.id} ${format(run.responses[d.id])}${d.unit?' '+d.unit:''}`).join(' · '));text.append(element('small','','已选工况'),label,values);const button=element('button','','查看模型');button.type='button';button.disabled=!run.viewIds?.length;button.title=button.disabled?'该工况尚无可用模型':'查看所选工况的真实模型';button.addEventListener('click',()=>this.selectRun(run.id,true));this.selectionBar.replaceChildren(text,button);
 }
 renderControls(entry){
  if(entry.body.contains(document.activeElement))return;
  const controls=entry.node.ids.map(id=>this.context.controls.find(c=>c.id===id)).filter(Boolean).map(c=>c.group===entry.node.title?{...c,group:''}:c);
  renderParameterPanel(entry.body,controls,c=>c.parameter?this.context.parameters[c.id]:c.id==='view'?this.context.state.view:this.context.state[c.id],'adaptive-'+entry.node.id+'-');
 }
 async dataset(id,context){
  const key=JSON.stringify([context.taskId,context.uiRevision,context.deliveryVersion,id,this.document?.datasets?.[id]]);
  if(!this.datasetCache.has(key)){this.datasetCache.set(key,context.getDataset(id).catch(error=>{this.datasetCache.delete(key);throw error;}));while(this.datasetCache.size>8)this.datasetCache.delete(this.datasetCache.keys().next().value);}
  return this.datasetCache.get(key);
 }
 async renderData(){
  const generation=++this.generation,context=this.context;this.ready=false;
  const sourceContext={...context,getDataset:id=>this.dataset(id,context)};
  const actions=[...this.nodes.values()].filter(e=>e.action).map(e=>e.action);
  await Promise.all([...actions,...[...this.nodes.values()].filter(e=>e.node.source||e.node.series).map(async entry=>{
   entry.element.setAttribute('aria-busy','true');for(const button of entry.exports?.children||[])button.disabled=true;
   try{
    const node=entry.node;
    if(node.type==='heatmapChart'){
     const table=await resolveSource(node.source,sourceContext);if(generation!==this.generation)return;entry.table=table;this.paintChart(entry,[{table}]);
    }else if(node.series){
     const series=await Promise.all(node.series.map(async s=>({...s,table:await resolveSource(s.source,sourceContext)})));if(generation!==this.generation)return;
     this.paintChart(entry,series);
     entry.table=chartDataTable(series);
    }else{
     const table=await resolveSource(node.source,sourceContext);if(generation!==this.generation)return;entry.table=table;
     if(node.type==='metric'){
      const column=node.column||'value';if(!table.columns.some(c=>c.id===column))throw new Error('指标引用不存在的数据列：'+column);
      const values=table.rows.map(r=>r[column]).filter(v=>typeof v==='number'&&Number.isFinite(v));
      const kind=node.reducer||'last',value=!values.length?null:kind==='last'?values.at(-1):kind==='mean'?values.reduce((a,b)=>a+b,0)/values.length:values.reduce((a,b)=>kind==='min'?Math.min(a,b):Math.max(a,b));
      const unit=node.unit??table.columns.find(c=>c.id===column)?.unit??'';entry.body.replaceChildren(element('strong','adaptive-metric',values.length?format(value):'—'),element('span','adaptive-unit',values.length?unit:'暂无有效值'));
     }else this.renderTable(entry);
    }
    entry.error=null;for(const button of entry.exports?.children||[])button.disabled=false;
   }catch(error){if(generation===this.generation)this.showError(entry,error);}
   finally{if(generation===this.generation)entry.element.setAttribute('aria-busy','false');}
  })]);
  if(generation===this.generation){this.syncSelection();this.ready=true;this.observe();this.onRendered?.();}
 }
 renderTable(entry){
  const table=entry.table;if(!table)return;const columns=tableColumns(table,entry.node),rows=tableRows(table,{query:entry.query,sort:entry.sort}),count=entry.node.pageSize||100;
  entry.page=Math.min(entry.page,Math.max(0,Math.ceil(rows.length/count)-1));const start=entry.page*count,rule=entry.node.highlight,valid=rule?table.rows.map(r=>r[rule.column]).filter(v=>typeof v==='number'&&Number.isFinite(v)):[],best=valid.length?(rule.mode==='min'?Math.min(...valid):Math.max(...valid)):null;
  entry.renderedRows=rows.slice(start,start+count);
  entry.body.innerHTML=`<div class="adaptive-table-scroll"><table><thead><tr>${columns.map(c=>`<th aria-sort="${entry.sort?.column===c.id?(entry.sort.direction==='asc'?'ascending':'descending'):'none'}"><button type="button" data-sort-column="${escape(c.id)}">${escape(c.label||c.id)}${c.unit?' ['+escape(c.unit)+']':''}${entry.sort?.column===c.id?(entry.sort.direction==='asc'?' ↑':' ↓'):''}</button></th>`).join('')}</tr></thead><tbody>${entry.renderedRows.map((r,i)=>`<tr${r.selection?` data-linked-row="${i}" data-linked-view="${escape(r.selection.view)}"${r.selection.time!==undefined?` data-linked-time="${r.selection.time}"`:''} tabindex="0"`:this.context?.study?.runs.some(run=>run.id===r.runId)?` data-chart-run="${escape(r.runId)}" tabindex="0"`:""}${rule&&best!==null&&r[rule.column]===best?' class="adaptive-row-best"':''}>${columns.map(c=>`<td style="text-align:${c.align||'right'}">${escape(formatCell(r[c.id],c))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const nav=element('div','adaptive-pagination'),previous=element('button','','上一页'),next=element('button','','下一页');previous.disabled=entry.page===0;next.disabled=start+count>=rows.length;previous.addEventListener('click',()=>{entry.page--;this.renderTable(entry);});next.addEventListener('click',()=>{entry.page++;this.renderTable(entry);});nav.append(previous,element('span','',rows.length?`${start+1}–${Math.min(start+count,rows.length)} / ${rows.length}`:'没有匹配数据'),next);entry.body.append(nav);this.syncSelection();
 }

 showError(entry,error){entry.error=String(error.message||error).slice(0,500);if(entry.body&&!['model','controls','button'].includes(entry.node.type))entry.body.replaceChildren(element('p','adaptive-error',entry.error));this.observe();}
 observe(){
  const state={revision:this.context?.uiRevision||0,panels:[...this.nodes.keys()],errors:[...this.nodes.values()].filter(e=>e.error||e.visibilityError).map(e=>({id:e.node.id,message:e.error||e.visibilityError}))},key=JSON.stringify([this.context?.taskId,state]);
  if(key!==this.lastObservation){this.lastObservation=key;this.onObserve?.(state);}
 }
 csv(){
  const entries=[...this.nodes.values()].filter(e=>e.table&&!e.error);if(!entries.length)throw new Error('当前面板没有可导出的数据');
  const rows=entries.flatMap(e=>e.table.rows.map((row,index)=>({panel:e.node.title||e.node.id,row:index,...Object.fromEntries(Object.entries(row).map(([k,v])=>['data.'+k,v]))}))),ids=[...new Set(rows.flatMap(Object.keys))];
  return new Blob([tableCSV({columns:ids.map(id=>({id})),rows})],{type:'text/csv;charset=utf-8'});
 }
 async image(){
  const box=this.host.getBoundingClientRect();if(!box.width||!box.height)throw new Error('展示面板当前不可见');
  const scale=Math.min(2,2400/box.width),canvas=document.createElement('canvas');canvas.width=Math.ceil(box.width*scale);canvas.height=Math.ceil(box.height*scale);const c=canvas.getContext('2d'),theme=this.theme();c.scale(scale,scale);c.fillStyle=theme.panel;c.fillRect(0,0,box.width,box.height);
  for(const entry of this.nodes.values()){
   if(containers.has(entry.node.type)||!entry.element.getClientRects().length)continue;
   const r=entry.element.getBoundingClientRect(),x=r.x-box.x,y=r.y-box.y;c.strokeStyle=theme.line;c.strokeRect(x+.5,y+.5,r.width-1,r.height-1);c.fillStyle=theme.ink;c.font='14px "Workbench CJK",system-ui';if(entry.node.title)c.fillText(entry.node.title,x+14,y+24);
   const svg=entry.body.querySelector('svg');
   if(entry.node.type==='model'){const source=this.getModelImage?.();if(source){const target=this.model.querySelector('#model-canvas').getBoundingClientRect();c.drawImage(source,target.x-box.x,target.y-box.y,target.width,target.height);}}
   else if(svg){const sr=svg.getBoundingClientRect();await paintSVG(c,svg,sr.x-box.x,sr.y-box.y,sr.width,sr.height);}
   else{const text=entry.body.innerText+(entry.node.type==='controls'?' '+[...entry.body.querySelectorAll('input,select')].map(i=>i.type==='checkbox'?String(i.checked):i.value).join(' / '):'');let py=y+(entry.node.title?48:24);for(const line of text.split('\n')){if(py>y+r.height-8)break;c.fillText(line,x+14,py,r.width-28);py+=20;}}
  }
  return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('面板导出失败')),'image/png'));
 }
}
