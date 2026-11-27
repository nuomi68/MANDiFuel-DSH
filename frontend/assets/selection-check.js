// The operator exercises one rendered control. A real user interaction takes
// precedence over both the check and its restoration.
export async function checkLinkedSelection({read,restore,current}){
 const before=read(),same=(a,b)=>a.view===b.view&&a.time===b.time&&a.run===b.run;
 if(!before.ready||!current())return {status:'unavailable'};
 const selector='[role=tab][data-select-view],[data-case-switch],[data-chart-point][data-linked-view],[data-chart-point][data-chart-run],tr[data-linked-view],tr[data-chart-run]';
 let candidate;
 for(const el of document.querySelectorAll(selector)){
  const d=el.dataset,view=d.selectView||d.linkedView,run=d.chartRun,time=d.linkedTime===undefined?undefined:Number(d.linkedTime);
  if(view===before.view&&(time===undefined||time===before.time)||!view&&(!run||run===before.run))continue;
  if(el.closest('[hidden]')||el.disabled||!el.getBoundingClientRect().width)continue;
  candidate={el,view,run,time};break;
 }
 if(!candidate)return {status:'not-applicable'};
 const {el,view,run,time}=candidate,component=el.closest('[data-ui-node]')?.dataset.uiNode;
 const snapshot=s=>({view:s.view,run:s.run,field:s.field,time:s.time,timeUnit:s.timeUnit,sampledRange:s.range});
 // Charts and tables can replace their DOM while loading the new frame.
 const selected=()=>Array.from(document.querySelectorAll(selector)).some(target=>{
  if(target.closest('[data-ui-node]')?.dataset.uiNode!==component)return false;
  const d=target.dataset;
  if(d.selectView)return d.selectView===view&&(target.getAttribute('aria-selected')==='true'||target.getAttribute('aria-pressed')==='true');
  return d.selected==='true'&&d.linkedView===el.dataset.linkedView&&d.linkedTime===el.dataset.linkedTime&&d.chartRun===el.dataset.chartRun;
 });
 let interrupted=false,attempted=false;
 const interrupt=event=>{if(event.isTrusted)interrupted=true;};
 const events=['pointerdown','keydown','wheel','input'];
 for(const type of events)document.addEventListener(type,interrupt,true);
 const active=()=>!interrupted&&current();
 const wait=async matches=>{
  const until=performance.now()+8000;
  while(active()&&performance.now()<until){
   const s=read();if(s.ready&&matches(s))return s;
   await new Promise(resolve=>setTimeout(resolve,50));
  }
 };
 let result={status:'failed',component,before:snapshot(before)};
 try{
  attempted=true;
  el.dispatchEvent(new MouseEvent('click',{bubbles:true}));
  const observed=await wait(s=>(!view||view===s.view)&&(!run||run===s.run)&&(time===undefined||s.time===time)&&!same(s,before)&&selected());
  if(observed)result={...result,status:'verified',observed:snapshot(observed)};
 }finally{
  try{
   if(attempted&&active()){
    await restore(before,active);
    const restored=await wait(s=>same(s,before)&&s.field===before.field);
    result.restored=!!restored;
    if(!restored)result.status='failed';
   }
   if(!active())result.status='interrupted';
  }finally{for(const type of events)document.removeEventListener(type,interrupt,true);}
 }
 return result;
}
