import {randomUUID} from 'node:crypto';
// UI children belong to a private, unprompted presentation owner.
// Solver agents receive no UI instructions, child lineage, or completion messages.
// Coalesce observations; only one presentation child runs per main session at a time.
import {readFrontendRole,AGENT_RESULT_SCHEMA,SKILL} from './frontend-agent.mjs';
import {attachFrontendTools,renderConfirmation,verifyRenderedSelection,selectionConfirmed} from './frontend-tools.mjs';
import {comparisonReview,missingComparison} from './scientific-comparison.mjs';
function containsModel(node){return node?.type==='model'||(node?.children||[]).some(containsModel);}
const UPDATE_KEYS={parameters:{type:'array'},controls:{type:'array'},rendering:{type:'object'},parameterValues:{type:'object'},viewState:{type:'object'},interactions:{type:'array'},ui:{oneOf:[{type:'object'},{type:'null'}]},exports:{type:'array'},defaultView:{type:'string'},study:{type:'string'},studyMapping:{type:'object'},deliveryRequirements:{type:'object'},panelTitle:{type:'string'},panelDescription:{type:'string'}};
export const SCHEMA={type:'object',properties:{update:{type:'object',properties:UPDATE_KEYS,additionalProperties:false}},required:['update'],additionalProperties:false};
export async function publishUpdate(call,id,update){
 update={...update};delete update.progress;
 const path=`/api/tasks/${id}/present`;
 if(update.ui!==undefined&&update.exports?.length){
  const {ui,progress,...model}=update;
  const published=await call(path,model);if(published.importError)throw new Error(published.importError);
  // An optional chart/schema failure must not strand a valid physical model
  // on its earlier preview field. The failed UI still receives normal repair.
  return call(path,{ui,...progress?{progress}:{}});
 }
 return call(path,update);
}
export function mountPresenter(ctx,call,resolveTask,{timeoutMs=300000,maxWorkers=2}={}){
 const states=new Map(),observedTasks=new Map(),activeWorkers=new Set(),owners=new Map();let closed=false;
 // The packaged plugin requires tools. Direct legacy embedders retain their
 // earlier return-update protocol; production uses the scoped operator tools.
 const toolMode=!!ctx.tools;
 ctx.on('agent/created',({agent})=>{
  const state=owners.get(String(agent.session.header.parentSession));
  if(!state?.toolSession)return;
  const session=state.toolSession;
  attachFrontendTools(agent,{id:state.taskId,call,session,current:()=>!closed&&state.toolSession===session&&!state.controller?.signal.aborted});
 });
 const stateFor=id=>{if(!states.has(id))states.set(id,{taskId:id,agent:null,busy:false,revision:null,lastRun:0,settled:false});return states.get(id);};
 async function pump(state){
  if(closed||state.busy||Date.now()<(state.retryAt||0))return;state.busy=true;
  const requestEpoch=state.requestEpoch||0,superseded=()=>requestEpoch!==(state.requestEpoch||0);
  const displayRequestRevision=state.displayRequestRevision;
  const publishState=async(id,value)=>{
   if(superseded())return;
   const payload={...value};
   if(displayRequestRevision!==undefined)payload.displayRequestRevision=displayRequestRevision;
   if(value.state==='idle'&&state.lastDataRevision)payload.dataRevision=state.lastDataRevision;
   if(state.operator)payload.operator=state.operator;
   const endsDisplayRequest=displayRequestRevision!==undefined&&['idle','warning','error'].includes(value.state);
   try{await call(`/api/tasks/${id}/presenter`,payload);}
   catch{
    if(endsDisplayRequest&&!superseded())state.pendingDisplayReceipt=payload;
    return;
   }
   if(endsDisplayRequest&&!superseded()){
    delete state.displayRequestRevision;
    delete state.pendingDisplayReceipt;
   }
  };
  try{
   const id=state.taskId;
   if(state.pendingDisplayReceipt){await publishState(id,state.pendingDisplayReceipt);return;}
   let facts=await call(`/api/tasks/${id}/observe`);
   if(superseded())return;
   state.lastDataRevision=facts.dataRevision;
   if(!state.initialized){
    state.initialized=true;
    const saved=facts.presenter;
    if(!state.displayRequest&&!state.triggeredByFiles&&saved?.state==='idle'&&saved.dataRevision===facts.dataRevision&&facts.dataRevision&&['completed','failed','stopped','interrupted'].includes(facts.task.status)&&!facts.viewerState?.rendererError&&!(facts.uiState?.errors||[]).length){
     const review=toolMode?comparisonReview(facts):null;
     if(!missingComparison(review,saved.operator?.comparison?.exception,facts.task.latestRequest||facts.task.request)){
      state.revision=facts.revision;state.settled=true;state.settledDataRevision=facts.dataRevision;return;
     }
    }
   }
   if(state.settled){if(facts.dataRevision===state.settledDataRevision||facts.dataRevision===undefined&&facts.revision===state.revision)return;state.settled=false;state.uiRepairAttempts=0;state.awaitingUI=null;state.awaitingView=null;}
   const request=facts.task.latestRequest||facts.task.request||'';
   if(state.lastRequest!==request){state.lastRequest=request;state.uiRepairAttempts=0;state.awaitingUI=null;state.awaitingView=null;state.awaitingFrontend=null;}
   if(state.awaitingFrontend){
    const pending=state.awaitingFrontend,page=await call(`/api/tasks/${id}/frontend?target=page`),status=renderConfirmation(page,pending);
    if(superseded())return;
    if(status==='confirmed'){
     state.awaitingFrontend=null;
     const advanced=facts.dataRevision!==pending.dataRevision;
     const proof=advanced?null:await verifyRenderedSelection(pending,page,call,id);
     if(superseded())return;
     if(proof?.status==='failed')throw new Error('联动复验失败，请检查工况或保存帧绑定');
     if(pending.resumeAfterAck){
      state.revision=null;
      state.feedback='浏览器已连接。请对照当前请求核对已有组件，补齐仍未提交的内容。';
      await publishState(id,{state:'queued',message:'正在核对未完成的展示'});return;
     }
     const confirmed=!advanced&&selectionConfirmed(pending);
     if(confirmed&&!advanced)state.failures=0;
     if(state.operator)Object.assign(state.operator,{confirmed,...proof?{selectionCheck:proof}:{}});
     state.settled=!advanced&&['completed','failed','stopped','interrupted'].includes(facts.task.status);if(state.settled)state.settledDataRevision=facts.dataRevision;
     await publishState(id,{state:advanced?'queued':confirmed?'idle':'warning',message:advanced?'等待同步最新结果':confirmed?'前端操作已由页面确认':'页面已显示，本次工况或时刻切换尚未得到浏览器确认'});if(!advanced)return;
    }else if(status==='error'){
     state.awaitingFrontend=null;state.feedback=JSON.stringify({errors:page.browser?.errors,model:page.viewer?.rendererError});state.revision=null;state.uiRepairAttempts=(state.uiRepairAttempts||0)+1;
     if(state.uiRepairAttempts>2){state.settled=true;state.settledDataRevision=facts.dataRevision;await publishState(id,{state:'error',message:'前端操作修正仍未通过：'+state.feedback});return;}
    }else if(status==='stale'||facts.dataRevision!==pending.dataRevision){state.awaitingFrontend=null;state.revision=null;}
    else{if(Date.now()>pending.deadline&&!state.ackExpired){state.ackExpired=true;await publishState(id,{state:'warning',message:'配置已保存，页面尚未确认'});}return;}
   }
   let dataAdvanced=false;
   if(state.awaitingUI||state.awaitingView){
    const deliveredData=(state.awaitingUI||state.awaitingView).dataRevision;dataAdvanced=deliveredData!==undefined&&facts.dataRevision!==deliveredData;
    const uiReady=!state.awaitingUI||Number.isInteger(facts.uiState?.revision)&&facts.uiState.revision===state.awaitingUI.revision;
    const viewReady=!state.awaitingView||Number.isInteger(facts.viewerState?.revision)&&facts.viewerState.revision===state.awaitingView.revision;
    const errors=state.awaitingUI&&uiReady?[...(facts.uiState.errors||[])]:[];
    if((state.awaitingView&&viewReady||state.awaitingUI?.watchModel&&uiReady)&&facts.viewerState?.rendererError)errors.push({id:'model',message:facts.viewerState.rendererError});
    const deadline=state.awaitingUI?.deadline||state.awaitingView.deadline;
    if(errors.length){
     state.awaitingUI=null;state.awaitingView=null;
     const message=errors.map(e=>e.id+'：'+e.message).join('；');
     if((state.uiRepairAttempts||0)>=2){state.revision=facts.revision;state.settled=true;state.settledDataRevision=facts.dataRevision;await publishState(id,{state:'error',message:'展示修正仍未通过：'+message});return;}
     state.uiRepairAttempts=(state.uiRepairAttempts||0)+1;state.feedback='浏览器实际渲染反馈：'+message;state.revision=null;
    }else if(uiReady&&viewReady){state.awaitingUI=null;state.awaitingView=null;state.revision=facts.revision;state.settled=!dataAdvanced&&['completed','failed','stopped','interrupted'].includes(facts.task.status);await publishState(id,{state:dataAdvanced?'queued':'idle',message:dataAdvanced?'等待同步最新结果':'界面已显示'});if(state.settled)state.settledDataRevision=facts.dataRevision;if(!dataAdvanced)return;state.revision=null;}
    else if(Date.now()>=deadline){
     if(!dataAdvanced){if(!state.ackExpired)await publishState(id,{state:'warning',message:'配置已保存，浏览器尚未确认显示'});state.ackExpired=true;return;}
     state.awaitingUI=null;state.awaitingView=null;state.ackExpired=false;state.revision=null;
    }
    else return;
   }
   if(facts.revision===state.revision){state.settledDataRevision=facts.dataRevision;if(['completed','failed','stopped','interrupted'].includes(facts.task.status))state.settled=true;return;}
   const important=state.stage!==facts.stage;
   if(!important&&!dataAdvanced&&!state.feedback&&!state.displayRequest&&Date.now()-state.lastRun<12000){if(!state.queued){state.queued=true;await publishState(id,{state:'queued',message:'等待合并最新结果'});}return;}
   if(['failed','stopped','interrupted'].includes(facts.task.status)&&!state.triggeredByFiles&&!state.displayRequest&&!facts.task.displayOnly){
    await publishState(id,{state:'idle',message:'计算已结束，保留已有展示'});state.revision=facts.revision;state.settled=true;state.settledDataRevision=facts.dataRevision;return;
   }
   if(activeWorkers.size>=maxWorkers&&!activeWorkers.has(state)){if(!state.queued){state.queued=true;await publishState(id,{state:'queued',message:'等待更新展示'});}return;}state.queued=false;activeWorkers.add(state);
   state.revision=facts.revision;state.stage=facts.stage;state.lastRun=Date.now();state.configReady=false;
   const controller=new AbortController();state.controller=controller;state.operator=null;
   await publishState(id,{state:'running',message:'正在整理界面'});
   if(superseded())return;
   const agentOptions=state.agent?.options||ctx.agentDefaultModel?.currentSelection();
   if(!agentOptions?.provider||!agentOptions.model)throw new Error('展示模型尚未配置；请检查工作台默认模型设置');
   const role=readFrontendRole();
   const parent=await (state.ownerPromise??=ctx.agents.create({sessionId:'session-'+randomUUID(),meta:{origin:'subagent',cwd:process.env.MANDIFUEL_PRESENTER_WORKSPACE||process.cwd()},agentOptions,setup:agentCtx=>{agentCtx.systemPrompt.section({name:'mandifuel:presentation-isolated',order:0,text:role,complete:true});}}).catch(error=>{state.ownerPromise=null;throw error;}));
   if(superseded())return;
   const session=toolMode?{closed:false,request,cancel:()=>controller.abort(new Error('新的用户请求已替代当前前端操作'))}:null;state.toolSession=session;
   if(toolMode)owners.set(String(parent.agent.id),state);
   const prompt=toolMode?{request,requestKind:facts.task.displayOnly||state.displayRequest?'display-edit':'results',calculationRequest:facts.task.request,trigger:facts.stage,comparisonReview:comparisonReview(facts),skill:SKILL,currentPage:await call(`/api/tasks/${id}/frontend?target=page`),validationFeedback:state.feedback||null}:{...facts,validationFeedback:state.feedback||null,rejectedUpdate:state.rejectedUpdate||null};
   if(prompt.comparisonReview){
    const documents=facts.availableDocuments||[];
    const report=documents.find(path=>/^report\.md$/i.test(path))||(documents.length===1?documents[0]:null);
    if(report){
     try{
      const source=await call(`/api/tasks/${id}/frontend?target=data&node=${encodeURIComponent(report)}`);
      prompt.comparisonReview.report=source.document;
     }catch{prompt.comparisonReview.report={file:report,available:false};}
    }
   }
   if(superseded())return;
   const run=await ctx.subagents.start('spawn',{label:'前端操作',parent:parent.agent,signal:controller.signal,persona:role,toolFilter:{allow:[]},outputSchema:toolMode?AGENT_RESULT_SCHEMA:SCHEMA,prompt:[{type:'text',text:'读取前端技能并操作当前任务的授权插槽。\n'+JSON.stringify(prompt)}]});state.run=run;
   await publishState(id,{state:'running',sessionId:String(run.id),message:'正在整理界面'});
   let timer;const result=await Promise.race([run.result,new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('展示生成超时，将在后台有限重试；计算任务继续运行'));},timeoutMs);})]).finally(()=>clearTimeout(timer));
   if(superseded())return;
   if(toolMode){
    if(!session.toolsAttached)throw new Error('前端操作工具未绑定到私有会话');
    if(result.stopReason!=='completed'||!result.structured?.status)throw new Error(result.diagnostic||'前端操作会话未正常结束');
    if(!session.pageObserved||!session.skillLoaded)throw new Error('前端操作会话未读取技能与页面状态');
    const latest=await call(`/api/tasks/${id}/observe`),published=session.lastPublished;
    const status=result.structured.status;
    const summary=String(result.structured.summary||'').slice(0,500);
    state.operator={skill:SKILL.name,toolCalls:session.toolCalls||0,mutations:session.mutations||0,confirmed:false};
    if(session.applyError||status==='partial'||status==='applied'&&!published){
     throw new Error([summary,session.applyError||'本轮尚未完成提交','保留已生效的内容，先提交一个缺失组件，再继续。'].filter(Boolean).join('。'));
    }
    if(status==='blocked'){
     state.settled=latest.dataRevision===facts.dataRevision;state.settledDataRevision=facts.dataRevision;
     await publishState(id,{state:state.settled?'error':'queued',message:summary||'当前前端能力无法完成请求'});return;
    }
    // Verify even a no-op claim: the model may still be loading, or the page
    // may have disconnected since the child's last successful observation.
    const page=await call(`/api/tasks/${id}/frontend?target=page`),expected=published||session.renderExpected||page;
    const review=comparisonReview(latest),exception=result.structured.comparisonException;
    if(missingComparison(review,exception,latest.task.latestRequest||latest.task.request)){
     throw new Error('已有多个完成工况，当前页面还缺少工况比较图。读取 data 中的结果表和报告，选择可比输入与响应，先提交一幅有单位的真实数据图，再核对页面。显式格式限制或数据无法比较时填写 comparisonException。');
    }
    if(review)state.operator.comparison={...review,...exception?{exception}:{}};
    const confirmed=renderConfirmation(page,expected)==='confirmed',pending=!confirmed;
    // A pending plan is not a browser receipt for the already visible model.
    const waitingForReceipt=['pending','offline','selection-unconfirmed'].includes(session.renderStatus);
    if(status==='pending'&&!waitingForReceipt&&(!published||confirmed)){
     if(['completed','failed','stopped','interrupted'].includes(latest.task.status))throw new Error(summary||'计算已结束，请继续提交尚缺的展示内容');
     await publishState(id,{state:'waiting',message:summary||'等待计算结果'});return;
    }
    if(confirmed)await verifyRenderedSelection(session,page,call,id,controller.signal);
    if(session.selectionCheck?.status==='failed')throw new Error('联动复验失败，请检查工况或保存帧绑定');
    state.feedback=null;state.failedFeedback=null;state.retryAt=0;
    if(confirmed)state.failures=0;
    if(pending){state.awaitingFrontend={...expected,checkSelection:session.checkSelection,requireSelection:session.requireSelection,resumeAfterAck:status==='pending'&&!published,dataRevision:facts.dataRevision,deadline:Date.now()+30000};state.ackExpired=false;}
    state.settled=!pending&&latest.revision===facts.revision&&['completed','failed','stopped','interrupted'].includes(latest.task.status);if(state.settled)state.settledDataRevision=latest.dataRevision;
    state.triggeredByFiles=false;state.displayRequest=false;
    Object.assign(state.operator,{confirmed,...session.selectionCheck?{selectionCheck:session.selectionCheck}:{}});
    const advanced=latest.revision!==facts.revision;
    if(confirmed&&!selectionConfirmed(session)){
     state.operator.confirmed=false;state.settled=latest.dataRevision===facts.dataRevision;state.settledDataRevision=facts.dataRevision;
     await publishState(id,{state:'warning',message:'页面已显示，本次工况或时刻切换尚未得到浏览器确认'});return;
    }
    const visibleSummary=summary.trim().split(/\n\s*\n|(?<=[。！？])/,1)[0]||'界面已确认';
    await publishState(id,{state:pending?'waiting':advanced?'queued':'idle',sessionId:String(run.id),message:pending?'配置已保存，等待页面确认':advanced?'等待同步最新结果':visibleSummary});
    return;
   }
   if(result.stopReason!=='completed'||!result.structured?.update)throw new Error(result.diagnostic||'展示子任务未能生成有效配置（'+result.stopReason+'）');
   state.configReady=true;state.triggeredByFiles=false;state.displayRequest=false;const latest=await call(`/api/tasks/${id}/observe`),update=structuredClone(result.structured.update);
   state.candidate=update;
   // A newer explicit layout wins over a child that started from the old UI.
   if((latest.presentation?.uiRevision||0)!==(facts.presentation?.uiRevision||0))delete update.ui;
   // A late child may still supply useful controls, but may not regress progress.
   if(latest.revision!==facts.revision){delete update.progress;delete update.exports;delete update.defaultView;delete update.deliveryRequirements;if(latest.task.latestRequest!==facts.task.latestRequest){delete update.rendering;delete update.controls;delete update.parameterValues;delete update.viewState;delete update.panelTitle;delete update.panelDescription;delete update.ui;delete update.studyMapping;}}
   else if(facts.deliveryRequirements&&Object.keys(facts.deliveryRequirements).length)update.deliveryRequirements={...update.deliveryRequirements,...facts.deliveryRequirements};
   const published=await publishUpdate(call,id,update);if(published.importError)throw new Error(published.importError);state.feedback=null;state.failedFeedback=null;state.rejectedUpdate=null;state.failures=0;state.retryAt=0;
   if(update.ui)state.awaitingUI={revision:published.uiRevision,watchModel:containsModel(update.ui.root),dataRevision:facts.dataRevision,deadline:Date.now()+30000};
   if(update.viewState&&published.modelReady)state.awaitingView={revision:published.viewStateRevision,dataRevision:facts.dataRevision,deadline:Date.now()+30000};
   const waiting=!!(state.awaitingUI||state.awaitingView);
   if(waiting)state.ackExpired=false;
   const advanced=latest.revision!==facts.revision;
   await publishState(id,{state:published.importError?'warning':waiting?'waiting':advanced?'queued':'idle',sessionId:String(run.id),message:published.importError||(waiting?'界面配置已保存，等待页面确认':advanced?'等待同步最新结果':'界面已同步')});
   state.settled=!state.awaitingUI&&!state.awaitingView&&latest.revision===facts.revision&&['completed','failed','stopped','interrupted'].includes(latest.task.status);if(state.settled)state.settledDataRevision=latest.dataRevision;
  }catch(error){if(superseded())return;const message=String(error.message||error);state.failures=(state.failures||0)+1;if(state.configReady)state.rejectedUpdate=state.candidate;if(state.failures<=2){state.failedFeedback=message;state.feedback=message;state.revision=null;state.settled=false;state.retryAt=Date.now()+5000*state.failures;}else{state.settled=true;state.settledDataRevision=state.lastDataRevision;}if(state.taskId&&!closed)await publishState(state.taskId,{state:state.failures<=2?'queued':'error',message,...state.failures<=2?{retryAt:state.retryAt}:{}});}
  finally{const run=state.run;if(state.toolSession)state.toolSession.closed=true;state.toolSession=null;state.run=null;state.controller=null;state.busy=false;activeWorkers.delete(state);if(run)void run.dispose().catch(()=>{});}
 }
 const notify=agent=>{
  if(closed||agent.session.header.origin==='subagent')return;
  void Promise.resolve(resolveTask(agent)).then(id=>{
   if(!id||closed)return;const state=stateFor(id);state.agent=agent;
   if(agent.status==='running')state.settled=false;
   if(agent.status==='idle'&&state.controller)void call(`/api/tasks/${id}/observe`).then(f=>{if(agent.status==='idle'&&['failed','stopped','interrupted'].includes(f.task.status)&&!f.task.displayOnly)state.controller?.abort();}).catch(()=>{});
   void pump(state);
  }).catch(()=>{});
 };
 const discover=async()=>{
  for(const agent of ctx.agents?.roots?.()||[])if(agent.session.header.origin!=='subagent'&&![...states.values()].some(s=>s.agent===agent))notify(agent);
  const tasks=await call('/api/tasks');
  if(!Array.isArray(tasks)){
   // Older embedders expose individual observations without a task index.
   for(const state of states.values())if(state.settled)void pump(state);
   return;
  }
  for(const task of tasks){
   if(task.draft)continue;
   const previous=observedTasks.get(task.id);
   const data=JSON.stringify([task.workspaceRevision||0,task.evidence?.revision,task.study?.version,task.status]);
   observedTasks.set(task.id,{data,issue:task.renderIssue});
   const changed=previous&&previous.data!==data;
   const savedRequest=task.presenter?.displayRequestRevision;
   const missed=!previous&&(savedRequest!==undefined||(task.workspaceRevision||0)>0&&task.status&&task.presenter?.state!=='idle');
   const newError=task.renderIssue&&task.renderIssue!==previous?.issue;
   if(!changed&&!missed&&!newError)continue;
   const state=stateFor(task.id);
   if(!changed&&!missed&&(state.busy||state.awaitingFrontend||state.failures>2||state.uiRepairAttempts>2))continue;
   if(missed&&savedRequest!==undefined&&state.displayRequestRevision===undefined){
    state.displayRequestRevision=savedRequest;state.displayRequest=true;
   }
   state.triggeredByFiles=true;state.settled=false;
   if(changed||missed){state.uiRepairAttempts=0;state.failures=0;state.retryAt=0;}
   void pump(state);
  }
 };
 const timer=setInterval(()=>{void discover().catch(()=>{});for(const state of states.values())if(!state.settled||state.pendingDisplayReceipt)void pump(state);},3000);void discover().catch(()=>{});
 const reviewedOnOpen=new Set();
 async function reviewSaved(id){
  if(!toolMode||closed||states.has(id)||reviewedOnOpen.has(id))return;
  reviewedOnOpen.add(id);
  try{
   const facts=await call(`/api/tasks/${id}/observe`);
   if(closed||states.has(id)||facts.presenter?.state!=='idle')return;
   const review=comparisonReview(facts);
   if(missingComparison(review,facts.presenter.operator?.comparison?.exception,facts.task.latestRequest||facts.task.request))void pump(stateFor(id));
  }catch{reviewedOnOpen.delete(id);}
 }
 ctx.on('agent/disposed',({agent})=>{for(const state of states.values())if(state.agent===agent)state.agent=null;});
 ctx.effect(()=>async()=>{closed=true;clearInterval(timer);const runs=[];for(const s of states.values()){s.controller?.abort();if(s.run)runs.push(s.run.dispose());if(s.ownerPromise)runs.push(s.ownerPromise.then(h=>h.dispose()));}await Promise.allSettled(runs);states.clear();owners.clear();});
 return {notify,reviewSaved,request(id,displayRequestRevision){
  const state=stateFor(id);state.requestEpoch=(state.requestEpoch||0)+1;
  state.displayRequestRevision=displayRequestRevision;delete state.pendingDisplayReceipt;
  state.controller?.abort(new Error('新的显示请求已替代当前前端操作'));state.awaitingFrontend=null;state.awaitingUI=null;state.awaitingView=null;state.uiRepairAttempts=0;state.settled=false;state.displayRequest=true;state.failures=0;state.feedback=null;state.failedFeedback=null;state.retryAt=0;state.revision=null;void pump(state);
 }};
}
