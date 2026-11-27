// Evidence values and statuses come only from the independent verifier.
export const evidenceLabels={verified:'本项通过',failed:'超出本项标准',not_verified:'未核验',not_applicable:'不适用',computed:'原场计算',stale:'证据已变化',pending:'等待核查',ready:'核查记录已就绪',idle:'暂无核查记录',error:'核查暂不可用'};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
export const evidenceNumber=value=>typeof value==='number'?(value!==0&&(Math.abs(value)<.001||Math.abs(value)>=1e5)?value.toExponential(6):Number(value.toPrecision(8)).toString()):'—';
const unitLabel=unit=>unit==='1'?'（无量纲）':unit;
export function evidenceLink(claim,open,label){
 const button=el('button',label??(claim.title+' · '+evidenceNumber(claim.value)+' '+unitLabel(claim.unit)+(claim.status==='stale'?'（证据已变化）':'')),'evidence-claim-link');button.type='button';button.dataset.evidenceId=claim.id;button.title='查看响应定义、核查范围和原始文件';button.addEventListener('click',()=>open(claim.id));return button;
}
// Only execution receipts with the same meaning may share a summary.
export function evidenceGroups(claims){
 const groups=[],endpoints=new Map();
 for(const claim of claims){
  if(claim.key!=='execution.final_time'){groups.push([claim]);continue;}
  const key=JSON.stringify([claim.value,claim.unit,claim.timeUnit,claim.status,claim.execution]);
  if(!endpoints.has(key)){const group=[];endpoints.set(key,group);groups.push(group);}
  endpoints.get(key).push(claim);
 }
 const priority=([c])=>(['failed','stale','not_verified'].includes(c.status)?0:2)+Number(c.key==='execution.final_time');
 return groups.sort((a,b)=>priority(a)-priority(b));
}
function status(value){const n=el('span',evidenceLabels[value]||value,'evidence-status');n.dataset.state=value;return n;}
function describe(value){return typeof value==='string'?value:JSON.stringify(value,null,2);}

export class EvidenceBrowser{
 constructor({button,dialog,onData}){
  Object.assign(this,{button,dialog,onData});this.task=null;this.data=null;this.indexRequest=null;this.detailRequest=null;this.selected=null;this.map=new Map();this.loaded=null;
  this.content=dialog.querySelector('[data-evidence-content]');this.subtitle=dialog.querySelector('[data-evidence-subtitle]');
  button.addEventListener('click',()=>this.open());dialog.querySelector('[data-evidence-close]').addEventListener('click',()=>dialog.close());
  dialog.querySelector('[data-evidence-back]').addEventListener('click',()=>{void this.open();});
  dialog.addEventListener('close',()=>{if(dialog.open)return;this.cancelDetail();button.setAttribute('aria-expanded','false');});
  this.timer=setInterval(()=>{if(this.dialog.open)this.refresh();},5000);
  window.addEventListener('pagehide',()=>{this.indexRequest?.abort();this.cancelDetail();clearInterval(this.timer);});
 }
 async api(query='',signal){const r=await fetch(`/workbench/api/tasks/${this.task.id}/evidence${query}`,{credentials:'same-origin',cache:'no-store',signal});const data=await r.json();if(!r.ok)throw new Error(data.error||'核查记录暂时无法读取');return data;}
 setTask(task){
  const changed=task?.id!==this.task?.id;this.task=task;this.button.disabled=!task;
  if(changed){this.indexRequest?.abort();this.indexRequest=null;this.cancelDetail();this.loaded=null;this.data=null;this.map=new Map();this.content.replaceChildren();if(this.dialog.open)this.dialog.close();}
  const key=task?JSON.stringify([task.id,task.evidence?.revision]):null;
  if(task&&key!==this.loaded){this.loaded=key;void this.refresh();}
 }
 cancelDetail(){
  this.detailRequest?.abort();this.detailRequest=null;this.selected=null;this.detailRevision=null;
 }
 async refresh(){
  if(!this.task||this.indexRequest)return;
  const controller=new AbortController();this.indexRequest=controller;
  const requested=this.loaded;
  try{
   const data=await this.api('',controller.signal);if(controller.signal.aborted)return;
   const changed=data.revision!==this.data?.revision;this.data=data;
   if(changed){this.map=new Map(data.claims.map(c=>[c.id,c]));this.onData?.();}
   if(this.dialog.open){
    if(this.selected){if(!this.detailRequest&&this.detailRevision!==this.claimRevision(this.selected))void this.select(this.selected);}
    else if(changed||!this.content.querySelector('.evidence-note'))this.renderIndex();
   }
  }catch(error){if(!controller.signal.aborted&&this.dialog.open&&!this.selected&&!this.data)this.content.replaceChildren(el('p',error.message));}
  finally{if(this.indexRequest===controller){this.indexRequest=null;if(requested!==this.loaded)void this.refresh();}}
 }
 claimRevision(id){
  const claim=this.map.get(id),row=claim&&this.data?.cases.find(c=>c.caseRoot===claim.caseRoot);
  return JSON.stringify([row?.revision,row?.state,claim?.status,claim?.execution]);
 }
 async open(id=null){
  if(!this.task)return;
  if(!this.dialog.open)this.dialog.show();
  this.button.setAttribute('aria-expanded','true');
  if(id&&id===this.selected&&this.detailRequest)return;
  this.cancelDetail();this.selected=id;
  this.dialog.querySelector('[data-evidence-back]').hidden=!id;
  if(!id&&this.data)this.renderIndex();
  else{this.subtitle.textContent=this.map.get(id)?.caseRoot||'';this.content.replaceChildren(el('p','正在读取原始证据核查记录…'));}
  if(id)await this.select(id);else await this.refresh();
 }
 renderIndex(){
  const data=this.data;if(!data)return;
  this.dialog.querySelector('[data-evidence-back]').hidden=true;
  this.subtitle.textContent=evidenceLabels[data.state]||data.state;this.content.replaceChildren(el('p','程序只读取输入、保存场与运行回执。每项结论的核查范围、容差和未验证内容分别列出。','evidence-note'));
  if(data.state==='pending')this.content.append(el('p','原始数据已变化或核查正在进行，旧记录暂不作为当前已核验结论。','evidence-note'));
  if(data.limits?.uncheckedCases)this.content.append(el('p','自动核查上限为 '+data.limits.automaticCaseLimit+' 个算例；另有 '+data.limits.uncheckedCases+' 个尚未自动核查，可用独立核查命令逐组检查。','evidence-note'));
  for(const item of data.cases){
   const section=el('section',undefined,'evidence-case');section.append(el('h3',item.caseRoot+' · 保存时刻 '+item.time));
   if(item.error)section.append(el('p',item.error,'evidence-note'));
   const claims=data.claims.filter(c=>c.caseRoot===item.caseRoot);
   if(claims.length){const table=el('table');const head=el('tr');for(const label of ['结论 / 物理量','本项核查','执行证据'])head.append(el('th',label));table.append(head);
    for(const claim of claims){const row=el('tr'),link=el('td'),check=el('td'),execution=el('td');link.append(evidenceLink(claim,id=>this.open(id)));check.append(status(claim.status));execution.append(status(claim.execution));row.append(link,check,execution);table.append(row);}section.append(table);
   }
   const pending=item.checks.filter(c=>['not_verified','failed','stale'].includes(c.status));
   if(pending.length)section.append(el('p','需关注：'+pending.map(c=>c.title+'（'+evidenceLabels[c.status]+'）').join('；'),'evidence-note'));
   this.content.append(section);
  }
  if(!data.cases.length)this.content.append(el('p','保存场到达并稳定后，独立程序会自动核查。网格预览和未求解的初值不作为已完成结果。'));
 }
 async select(id){
  const controller=new AbortController();this.detailRequest=controller;
  const revision=this.claimRevision(id);
  try{
   const data=await this.api('?claim='+encodeURIComponent(id),controller.signal);
   if(controller.signal.aborted||this.selected!==id)return;
   this.detailRevision=revision;this.renderDetail(id,data);
  }catch(error){if(!controller.signal.aborted&&this.selected===id)this.content.replaceChildren(el('p',error.message));}
  finally{if(this.detailRequest===controller)this.detailRequest=null;}
 }
 renderDetail(id,data){
  const q=data.claim;this.dialog.querySelector('[data-evidence-back]').hidden=false;this.subtitle.textContent=q.caseRoot;
  this.content.replaceChildren(el('h3',q.title));
  const context=el('p',evidenceNumber(q.value)+' '+unitLabel(q.unit)+' · 保存时刻 '+q.time+' '+(q.timeUnit||'单位未核实'));context.append(document.createTextNode(' '),status(q.status));this.content.append(context);
  if(data.state!=='ready')this.content.append(el('p','原始证据已变化；以下为历史核查定义，不能当作当前已核验结果。','evidence-note'));
  this.content.append(el('h4','响应定义'),el('p','算例：'+q.caseRoot),el('p','运算：'+q.definition.operation),el('pre','选择范围：'+describe(q.definition.selection)+'\n单位：'+q.definition.unit,'evidence-definition'));
  if(q.note)this.content.append(el('p',q.note,'evidence-note'));
  this.content.append(el('h4','已核验与尚未核验的项目'));
  for(const check of data.checks){
   const box=el('details',undefined,'evidence-check');box.open=q.checks.includes(check.id)||check.key==='execution';
   const summary=el('summary',check.title+' ');summary.append(status(check.status));box.append(summary);
   if(check.reason)box.append(el('p',check.reason));if(check.scope)box.append(el('p','范围：'+check.scope));
   for(const [key,label]of [['formula','计算式'],['metric','实际核对量'],['tolerance','本项标准'],['assumptions','适用条件']])if(check[key]&&JSON.stringify(check[key])!=='[]')box.append(el('p',label),el('pre',describe(check[key])));
   this.content.append(box);
  }
  if(q.samples){const samples=el('details');samples.append(el('summary','同位置的代表样本与最大误差样本'),el('pre',describe(q.samples)));this.content.append(samples);}
  this.content.append(el('h4','原始文件与内容指纹'));
  const files=el('div',undefined,'evidence-sources');for(const source of data.sources){
   const item=el('details'),summary=el('summary',source.path);item.append(summary,el('small',source.role),el('code','SHA-256 '+source.sha256));
   const button=el('button','查看原文件','text-button compact');button.type='button';button.dataset.evidenceSource=source.id;
   button.addEventListener('click',async()=>{button.disabled=true;try{const s=await this.api('?claim='+encodeURIComponent(id)+'&source='+encodeURIComponent(source.id));const pre=el('pre',(s.changed?'文件已变化，下面是当前内容；原核查记录已过期。\n\n':'')+s.text+(s.truncated?'\n…仅预览前 128 KiB':''));item.append(pre);}catch(error){item.append(el('p',error.message));}finally{button.remove();}});
   item.append(button);files.append(item);
  }this.content.append(files);
  this.content.append(el('p','核查程序 '+data.engine+' · 记录生成于 '+new Date(data.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）','evidence-note'));
 }
}
