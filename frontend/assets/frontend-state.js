// Observe only owned workbench surfaces. Never enter the native DSH iframe.
const box=element=>{const r=element?.getBoundingClientRect();return{x:Math.round(r?.x||0),y:Math.round(r?.y||0),width:Math.round(r?.width||0),height:Math.round(r?.height||0)};};
const visible=element=>!!element&&!element.closest('[hidden]')&&element.getBoundingClientRect().width>0&&element.getBoundingClientRect().height>0;
function coverage(element){
 const r=element.getBoundingClientRect(),inViewport=r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth,covered=new Set();
 if(visible(element)&&inViewport)for(const f of [.25,.5,.75]){
  const x=Math.max(1,Math.min(innerWidth-1,r.left+r.width*f)),y=Math.max(1,Math.min(innerHeight-1,r.top+r.height*f)),top=document.elementFromPoint(x,y);
  if(!top||element.contains(top)||top.contains(element))continue;
  const owner=top.closest('[data-ui-node]');if(owner)covered.add(owner.dataset.uiNode);else if(top.closest('#drawer'))covered.add('settings-drawer');
 }
 return{inViewport,coveredBy:[...covered].slice(0,3)};
}
export function captureFrontendState({task,state,adaptive,style}){
 const nodes=[...(adaptive?.nodes?.values()||[])].slice(0,64).map(entry=>({id:entry.node.id,type:entry.node.type,visible:visible(entry.element),rect:box(entry.element),...coverage(entry.element),...(entry.activeTab?{activeTab:entry.activeTab}:{}),...(entry.node.type==='table'?{table:{query:(entry.query||'').slice(0,200),page:entry.page||0,rows:Math.min(20000,entry.table?.rows?.length||0),sort:entry.sort||null}}:{}),...(entry.interaction?{chart:{viewport:entry.interaction.viewport,hiddenSeries:[...entry.interaction.hidden]}}:{})}));
 const slot=id=>{const element=document.querySelector(id);return{visible:visible(element),rect:box(element)};};
 const selection=Object.fromEntries(['run','panel','field','view','frame'].map(k=>[k,state[k]??null]));selection.settingsOpen=document.querySelector('#drawer')?.open===true&&document.querySelector('#drawer')?.dataset.view==='settings';
 const display=Object.fromEntries(['mesh','extrema','cut','cutAngle','cameraView','aspectMode','displayMode','sliceAxis','slicePosition','compare','compareField','scale','colorMin','colorMax'].map(k=>[k,state[k]??null]));if(style)display.appearance=style;
 const mapping=document.querySelector('#model-canvas')?.dataset.fieldMapping;if(mapping)display.fieldMapping=JSON.parse(mapping);
 const stage=document.querySelector('#model-stage'),model={visible:visible(stage),ready:!!stage&&!stage.classList.contains('unready')&&document.querySelector('#viewer-error')?.hidden!==false,kind:stage?.classList.contains('unready')?'pending':stage?.classList.contains('mesh-preview')?'mesh':'fields',view:state.view||null,field:state.field||null};
 return{model,revision:task.presentation?.uiRevision||0,presentationVersion:task.presentationVersion||0,interactionRevision:task.presentation?.interactionRevision||0,ready:!adaptive?.document||adaptive.ready,panels:nodes.map(n=>n.id),errors:[...(adaptive?.nodes?.values()||[])].filter(e=>e.error||e.visibilityError).map(e=>({id:e.node.id,message:e.error||e.visibilityError})),viewport:{width:window.innerWidth,height:window.innerHeight,dpr:window.devicePixelRatio,scrollX:window.scrollX,scrollY:window.scrollY},slots:{main:slot('.model-column'),aside:slot('#adaptive-aside'),settings:slot('#drawer'),model:slot('#model-stage'),conversation:slot('#conversation-column')},nodes,selection,parameters:{...state.parameters},display};
}

export class FrontendStateObserver{
 constructor({context,send}){
  this.context=context;this.send=send;this.timer=null;
  const schedule=()=>this.schedule();
  for(const event of ['click','input','change','pointerup','wheel','keyup'])document.addEventListener(event,schedule,{passive:true});
  window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,{passive:true});
  this.heartbeat=setInterval(()=>this.schedule(),5000);
 }
 schedule(){if(this.timer)return;this.timer=setTimeout(()=>{this.timer=null;try{const c=this.context();if(c?.task)void this.send(c.task.id,captureFrontendState(c));}catch{/* Rendering errors are reported by the existing viewer path. */}},120);}
}
