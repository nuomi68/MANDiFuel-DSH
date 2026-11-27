// Mount only DSH-authored contracts in the workbench's existing parameter and result slots.
import {parameterMarkup} from './parameter-panel.js';

export class SimulationApp {
 constructor({token,onUpdate,onSelection,observation}){
  Object.assign(this,{token,onUpdate,onSelection,observation});this.cache=new Map();this.key='';this.data=null;this.epoch=0;
 }
 bind(task,view){
  const key=task&&view?.kind==='results'&&view.caseRoot?JSON.stringify([task.id,view.caseRoot]):'';
  const sourceVersion=JSON.stringify([task?.status,task?.modelVersion,view?.version]);
  if(this.sourceVersion!==sourceVersion)this.available=undefined;
  this.sourceVersion=sourceVersion;this.taskStatus=task?.status;this.taskId=task?.id;this.viewId=view?.id;
  if(this.key===key)return;
  this.available=undefined;this.reason='';this.buildError='';this.readError='';
  this.key=key;this.epoch++;this.data=null;this.form?.remove();this.form=null;this.builder=null;this.cache=new Map();this.signature='';this.busy=false;
  this.picker?.remove();this.picker=null;clearTimeout(this.timer);
  if(!key)return;
  this.endpoint='/workbench/api/tasks/'+encodeURIComponent(task.id)+'/calculator';this.root=view.caseRoot;
  try{this.saved=JSON.parse(localStorage.getItem('simulation-app:'+key))||{};}catch{this.saved={};}
  this.loadingCandidate=false;
  if(this.saved.blocked==='正在回读候选输入卡')this.saved.blocked='候选回读中断，请重新选择';
  this.selected=this.saved.run||'baseline';void this.poll(this.epoch);
 }
 get spec(){return this.data?.spec;}
 get history(){return (this.data?.runs||[]).filter(r=>r.status==='completed');}
 // Each completed recalculation stores its field alongside the scalar and
 // profile results, including when the generated contract only requests tables.
 get fieldRun(){return this.spec&&this.selected!=='baseline'&&this.history.some(run=>run.id===this.selected)?this.selected:null;}
 remember(){if(this.key)localStorage.setItem('simulation-app:'+this.key,JSON.stringify(this.saved));}
 async api(query={},body){
  const url=this.endpoint+'?'+new URLSearchParams({case:this.root,...query});
  const res=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':this.token()},body:JSON.stringify({...body,case:this.root})}:{});
  const result=await res.json();if(!res.ok)throw Error(result.error||'读取应用失败');return result;
 }
 async poll(epoch){
  const inspect=this.taskStatus==='completed'&&!this.spec&&this.available===undefined;
  try{const data=await this.api(inspect?{inspect:1}:{});if(this.epoch===epoch){
   if(this.readError){this.readError='';this.signature='';}
   if(inspect){this.available=data.available??!!data.spec;this.reason=data.reason||'';}
   this.accept(data);
   if(this.spec&&this.token()&&!document.hidden){
    const components=this.spec.components.map(c=>c.id).filter(id=>{
     const node=document.querySelector('[data-ui-node="app-'+this.spec.appId+'-'+id+'"]');
     return node?.querySelector('svg,table')&&node.getAttribute('aria-busy')!=='true';
    });
    const feedback=this.observation();
    await this.api({},{action:'observed',version:this.spec.version,run:this.selected,components,
     draftValues:Object.fromEntries(this.spec.parameters.map(p=>[p.id,this.value(p)])),candidate:this.saved.candidate?.caseRoot,canRun:this.canRun(),
     field:feedback.field,ready:feedback.ready&&components.length===this.spec.components.length&&(!(this.fieldRun||this.spec.outputs.some(o=>o.kind==='field'))||feedback.field)});
   }
  }}
  catch(error){if(this.epoch===epoch){if(this.spec)this.status(error.message);else{this.readError=error.message;this.onUpdate();}}}
  finally{if(this.epoch===epoch)this.timer=setTimeout(()=>this.poll(epoch),3000);}
 }
 accept(data){
  const signature=JSON.stringify(data);if(signature===this.signature)return;
  if(this.spec&&data.spec&&(data.spec.version<this.spec.version||data.runs.length<this.data.runs.length))return;
  if(this.data?.runs.some(r=>r.status!=='running'&&data.runs.some(n=>n.id===r.id&&n.status==='running')))return;
  const was=this.spec;this.data=data;this.signature=signature;
  if(!this.spec&&!was){this.onUpdate();return;}
  if(!this.history.some(r=>r.id===this.selected))this.selected='baseline';
  this.saved.run=this.selected;this.remember();this.syncPicker();this.onUpdate();
 }
 select(id){
  if(!this.history.some(r=>r.id===id)||this.selected===id)return;
  this.selected=id;this.saved.run=id;this.remember();this.syncPicker();
  if(this.form&&!this.saved.values)for(const p of this.spec.parameters)this.form.querySelector('[data-app-parameter="'+p.id+'"]').value=this.value(p);
  this.refreshForm();void this.onSelection();
 }
 name(run){return run.id==='baseline'?'原始工况':'复算 '+this.data.runs.indexOf(run);}
 syncPicker(){
  if(!this.spec){this.picker?.remove();this.picker=null;return;}
  if(!this.picker){
   this.picker=document.createElement('select');this.picker.className='text-button compact';this.picker.id='app-run';
   this.picker.setAttribute('aria-label','应用工况');this.picker.onchange=()=>this.select(this.picker.value);
   document.getElementById('parameters-button').before(this.picker);
  }
  this.picker.replaceChildren(...this.history.map(r=>new Option(this.name(r),r.id)));this.picker.value=this.selected;
 }
 artifact(run,kind){
  const key=JSON.stringify([run,kind]);if(!this.cache.has(key)){
   const cache=this.cache;cache.set(key,this.api({run,artifact:kind}).catch(e=>{cache.delete(key);throw e;}));
  }
  return this.cache.get(key);
 }
 value(p){return this.saved.values?.[p.id]??this.history.find(r=>r.id===this.selected)?.inputs[p.binding]??p.default;}
 canRun(){
  if(!this.spec||this.busy||this.saved.blocked||this.data.runs.some(r=>r.status==='running'))return false;
  const candidate=this.saved.candidate;
  if(candidate&&(candidate.appId!==this.spec.appId||candidate.version!==this.spec.version))return false;
  return this.spec.parameters.every(p=>{
   const raw=this.form?.querySelector('[data-app-parameter="'+p.id+'"]')?.value??this.value(p),value=Number(raw);
   return String(raw).trim()!==''&&Number.isFinite(value)&&value>=0&&(p.binding==='linearPower'||value>0)&&(!candidate||candidate.values[p.id]===value);
  });
 }
 blockDraft(reason){
  delete this.saved.candidate;this.saved.blocked=reason;this.remember();this.refreshForm();
 }
 async loadCandidate(caseRoot){
  const epoch=this.epoch,request=this.candidateRequest=Symbol();
  if(this.key&&!this.data){
   const data=await this.api();
   if(this.epoch!==epoch||request!==this.candidateRequest)return;
   this.accept(data);
  }
  if(!this.spec||this.busy)throw Error('请先打开已生成并空闲的计算器');
  const version=this.spec.version;
  this.loadingCandidate=true;this.blockDraft('正在回读候选输入卡');
  try{
   const draft=await this.api({candidate:caseRoot});
   if(epoch!==this.epoch||request!==this.candidateRequest)return;
   if(draft.appId!==this.spec?.appId||draft.version!==version||version!==this.spec.version)throw Error('候选契约已变化，请重新选择');
   this.saved.candidate=draft;this.saved.values={...draft.values};delete this.saved.blocked;delete this.saved.pending;
   for(const input of this.form?.querySelectorAll('[data-app-parameter]')||[])input.value=draft.values[input.dataset.appParameter];
   this.remember();
  }catch(error){if(epoch!==this.epoch||request!==this.candidateRequest)return;this.blockDraft(error.message);throw error;}
  finally{if(epoch===this.epoch&&request===this.candidateRequest){this.loadingCandidate=false;this.refreshForm();}}
 }
 status(text){if(this.form)this.form.querySelector('[role=status]').textContent=text;}
 get building(){return this.data?.build?.state==='building';}
 get buildNote(){
  if(this.buildError)return this.buildError;
  if(this.readError)return this.readError;
  if(this.building)return 'DSH 正在构建';
  if(this.data?.build?.state==='error')return '构建失败 · '+this.data.build.message;
  if(this.data?.build?.message)return this.data.build.message;
  return this.available===false?this.reason:'';
 }
 mountBuilder(host,plan={},saving=false,toggle){
  if(!this.builder){
   const form=document.createElement('form');this.builder=form;form.className='task-form';
   const label=document.createElement('label');label.textContent='希望开放哪些输入、展示哪些结果？';
   const request=document.createElement('textarea');request.maxLength=3000;request.rows=4;
   request.value=this.saved.buildText||'';request.placeholder='留空时，DSH 根据本题的计算需求选择。';
   request.oninput=()=>{this.saved.buildText=request.value;this.remember();};
   label.append(request);
   const submit=document.createElement('button');submit.type='submit';submit.className='text-button';
   const note=document.createElement('p');note.className='drawer-note';note.setAttribute('role','status');
   form.append(label,submit,note);
  }
  const form=this.builder,pending=['waiting','building'].includes(plan?.state);
  if(host.firstElementChild!==form)host.replaceChildren(form);
  form.querySelector('textarea').disabled=pending||saving;
  const submit=form.querySelector('button');
  submit.textContent=pending?'停止生成':'开启生成计算器';
  submit.disabled=saving||(!pending&&(!this.data||this.available===false));
  form.onsubmit=event=>{event.preventDefault();if(!submit.disabled)void toggle(!pending);};
  const note=form.querySelector('p'),message=plan?.message||this.buildNote||('基准工况 '+this.root+'。生成时读取已保存结果。');
  if(note.textContent!==message)note.textContent=message;
 }
 mount(host){
  const spec=this.spec,signature=JSON.stringify([this.key,spec.parameters,spec.title]);
  if(!this.form||this.formKey!==signature){
   this.formKey=signature;const form=document.createElement('form');form.id='simulation-parameters';form.className='parameter-group';
   const title=document.createElement('h3');title.textContent=spec.title;form.append(title);
   for(const p of spec.parameters){
    form.insertAdjacentHTML('beforeend',parameterMarkup({...p,type:'number',min:0},this.value(p),'app-'));
    const input=form.lastElementChild.querySelector('input');input.required=true;input.dataset.appParameter=p.id;delete input.dataset.control;
   }
   const button=document.createElement('button');button.type='submit';button.className='text-button';button.textContent='重新计算';form.append(button);
   const status=document.createElement('p');status.className='drawer-note';status.setAttribute('role','status');form.append(status);
   const evidence=document.createElement('div');evidence.className='parameter-readback';form.append(evidence);this.evidence=evidence;
   const custom=document.createElement('button');custom.type='button';custom.className='text-button';custom.textContent='使用当前输入作为自定义工况';custom.hidden=true;
   custom.onclick=()=>{this.candidateRequest=Symbol();delete this.saved.blocked;delete this.saved.candidate;this.remember();this.refreshForm();};
   form.insertBefore(custom,status);this.custom=custom;
   form.oninput=()=>{this.saved.values=this.readValues(true);this.remember();this.refreshForm();};
   form.onsubmit=e=>{e.preventDefault();void this.execute();};this.form=form;
  }
  if(host.firstElementChild!==this.form)host.replaceChildren(this.form);
  this.refreshForm();
 }
 readValues(text=false){return Object.fromEntries([...this.form.querySelectorAll('input')].map(i=>[i.dataset.appParameter,text?i.value:i.valueAsNumber]));}
 matchingRun(){
  const baseline=this.history.find(run=>run.id==='baseline');
  if(!baseline||!this.form)return null;
  const inputs={...baseline.inputs},values=this.readValues(),candidate=this.saved.candidate?.caseRoot;
  for(const p of this.spec.parameters)inputs[p.binding]=values[p.id];
  return this.history.find(run=>(!candidate||run.candidate===candidate||run.id==='baseline'&&this.spec.baseCase===candidate)&&
   Object.entries(inputs).every(([binding,value])=>run.inputs[binding]===value));
 }
 refreshForm(){
  if(!this.form||!this.spec)return;
  const run=this.history.find(r=>r.id===this.selected),last=this.data.runs.at(-1);
  const active=this.busy||this.data.runs.some(r=>r.status==='running');
  const canRun=this.canRun(),candidate=this.saved.candidate;
  const submit=this.form.querySelector('button[type=submit]'),match=this.matchingRun();
  submit.disabled=!canRun;submit.textContent=match?'查看已有结果':'重新计算';
  this.custom.hidden=active||this.loadingCandidate||(!this.saved.blocked&&(!candidate||canRun));
  const changed=this.spec.parameters.some(p=>Number(this.value(p))!==run?.inputs[p.binding]);
  this.status(active?'正在计算，保留已完成工况。':this.saved.blocked||(candidate?(canRun?'待算候选 '+candidate.caseRoot:'输入或契约已偏离所选候选，请重新选择或使用自定义工况'):last?.error||(changed?'输入已编辑':'当前输入'))+' · 当前查看 '+(run?this.name(run):'—')+' · 契约 v'+this.spec.version);
  this.evidence.replaceChildren();
  if(run)for(const [artifact,label] of [['readback','输入回读'],['receipt','执行回执'],['raw','原始场']]){
   const link=document.createElement('a');link.href=this.endpoint+'?'+new URLSearchParams({case:this.root,run:run.id,artifact});link.textContent=label;link.target='_blank';link.rel='noopener';this.evidence.append(link,'　');
  }
 }
 async execute(){
  if(!this.canRun())return;const epoch=this.epoch,version=this.spec.version,values=this.readValues(),candidate=this.saved.candidate?.caseRoot;
  const existing=this.matchingRun();
  if(existing){this.select(existing.id);this.refreshForm();this.status('已载入'+this.name(existing)+'的保存结果，求解启动次数不变。');return;}
  this.busy=true;this.refreshForm();
  const fingerprint=JSON.stringify([version,values,candidate]);
  if(this.saved.pending?.fingerprint!==fingerprint)this.saved.pending={fingerprint,id:crypto.randomUUID().replaceAll('-','')};
  this.remember();
  try{
   const record=await this.api({},{action:'run',version,values,candidate,requestId:this.saved.pending.id});
   if(this.epoch!==epoch)return;
   delete this.saved.pending;this.remember();this.busy=false;
   const next=await this.api();if(this.epoch!==epoch)return;this.accept(next);
   if(record.status==='completed'){delete this.saved.candidate;this.remember();this.select(record.id);}this.refreshForm();
  }catch(error){if(this.epoch===epoch){this.busy=false;if(candidate)this.blockDraft(error.message);else{this.refreshForm();this.status(error.message);}}}
 }
 compose(document){
  if(!this.spec?.components?.length)return document;
  const slots={main:[],aside:[]};
  for(const c of this.spec.components){
   const o=this.spec.outputs.find(x=>x.id===c.output),runs=c.scope==='history'?this.history:this.history.filter(r=>r.id===this.selected);
   const node={id:'app-'+this.spec.appId+'-'+c.id,type:c.type,title:c.title};
   const source=ids=>({kind:'appOutput',output:o.id,...(ids?{runs:ids}:{scope:c.scope}),app:this.spec.appId});
   if(c.type==='table')node.source=source();
   else if(o.kind==='profile')node.series=runs.map(r=>({label:this.name(r)+' · '+o.label,source:source([r.id]),x:c.x,y:c.y,marker:'circle'}));
   else node.series=[{label:o.label,source:source(),x:c.x,y:c.y,marker:'circle'}];
   if(c.type!=='table'){const names={radius:'半径 [m]',value:o.label+' ['+o.unit+']',case:'工况',...Object.fromEntries(this.spec.parameters.map(p=>[p.id,p.label+' ['+p.unit+']']))};node.xLabel=names[c.x];node.yLabel=names[c.y];}
   slots[c.slot].push(node);
  }
  const group=(slot,base)=>{const children=[...(base?[base]:[]),...slots[slot]];return children.length===1?children[0]:{id:'app-slot-'+this.spec.appId+'-'+slot,type:'column',children};};
  return {...(document||{mode:'below',scope:'all'}),root:group('main',document?.root),...(slots.aside.length?{aside:group('aside',document?.aside)}:{})};
 }
 async table(source){
  if(source.app!==this.spec?.appId)throw Error('应用工况已切换');
  const ids=source.runs||(source.scope==='history'?this.history.map(r=>r.id):[this.selected]);
  const query=new URLSearchParams({case:this.root,output:source.output});for(const id of ids)query.append('run',id);
  const response=await fetch(this.endpoint+'?'+query);const result=await response.json();
  if(!response.ok)throw Error(result.error||'无法读取应用输出');return result;
 }
}
