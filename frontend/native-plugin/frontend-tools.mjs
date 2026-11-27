import {SKILL,readSkill} from './frontend-agent.mjs';
import {caseTabs} from '../assets/ui-placement.js';

const object=(properties={},required=[])=>({type:'object',properties,required,additionalProperties:false});
export const TOOL_SCHEMAS={
 ui_read_skill:object({resource:{type:'string'}}),
 ui_calculator:object({case:{type:'string'},candidate:{type:'string'},components:{type:'array',items:{type:'object'}},version:{type:'integer'}},['case']),
 ui_inspect:object({target:{type:'string',enum:['page','main','aside','settings','model','data','capabilities','evidence']},node:{type:'string'}},['target']),
 ui_apply:object({expectedRevision:{type:'string'},operations:{type:'array',items:{type:'object'}},datasets:{type:'object'},update:{type:'object'}},['expectedRevision']),
 ui_wait_for_render:object({timeoutMs:{type:'integer'},verifySelection:{type:'boolean'}}),
};
const descriptions={ui_read_skill:'Read the registered frontend skill or one of its references. Read SKILL.md before mutations.',ui_inspect:'Inspect the actual current page, one slot, models, data or capabilities. Returns the revision required by ui_apply.',ui_apply:'Apply bounded slot operations and/or a presentation update to this task, using an inspected expectedRevision. Never writes solver inputs or saved fields.',ui_wait_for_render:'Check the browser acknowledgement and actual errors for the last mutation. Saving a configuration alone is not confirmation.'};
export function renderConfirmation(page,wanted){
 const browser=page.browser||{};
 if(!browser.connected)return'offline';
 const versions=[['revision','uiRevision'],['presentationVersion','presentationVersion'],['interactionRevision','interactionRevision']];
 if(versions.some(([observed,key])=>page[key]>wanted[key]||browser[observed]>wanted[key]))return 'stale';
 if(versions.some(([observed,key])=>(browser[observed]??0)<wanted[key]))return 'pending';
 const needsViewer=page.modelRequirement?.required!==false;
 if(needsViewer&&wanted.viewStateRevision&&page.viewer?.revision!==wanted.viewStateRevision)return 'pending';
 if(browser.errors?.length||needsViewer&&page.viewer?.rendererError)return 'error';
 if(page.modelRequirement?.required){
  if(browser.model?.visible===false)return 'error';
  if(!browser.model?.ready||browser.model.kind!==page.modelRequirement.kind)return 'pending';
 }
 return browser.ready===true?'confirmed':'pending';
}
const sleep=(ms,signal)=>new Promise((resolve,reject)=>{
 if(signal?.aborted)return reject(signal.reason||new Error('frontend operation cancelled'));
 const abort=()=>{clearTimeout(timer);reject(signal.reason||new Error('frontend operation cancelled'));};
 const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},ms);signal?.addEventListener('abort',abort,{once:true});
});

function changesSelectionBinding(node){
 if(!node||typeof node!=='object')return false;
 if(node.type==='tabs'&&caseTabs(node.children||[])||node.action?.state?.view||node.source?.selection||node.source?.runId||['study','history'].includes(node.source?.kind))return true;
 return (node.series||[]).some(changesSelectionBinding)||(node.children||[]).some(changesSelectionBinding);
}
export function selectionConfirmed(session){
 const status=session.selectionCheck?.status;
 if(session.requireSelection)return status==='verified';
 return !status||status==='verified'||status==='not-applicable';
}
export async function verifyRenderedSelection(session,page,call,id,signal){
 if(session.checkSelection&&!session.selectionCheck&&page.browser?.model?.kind==='fields'&&page.browser.browserId){
  const proof=await call('/api/tasks/'+id+'/selection-check',{revision:page.revision},signal);
  session.selectionCheck=proof;
 }
 return session.selectionCheck;
}

export function attachFrontendTools(agent,{id,call,current,session}){
 const revisions=new Set();let calls=0,mutations=0,skillLoaded=false;
 session.toolsAttached=true;
 for(const [name,parameters]of Object.entries(TOOL_SCHEMAS))agent.ctx.tools.register({
  name,description:name==='ui_calculator'?'Inspect the DSH-published app by caseRoot, or pass candidate to verify a prepared case before binding an appCandidate button. Read actual browser draftValues, candidate and canRun. Compose main/aside views from declared output IDs and the current version.':descriptions[name],parameters,
  output:{schema:{type:'object'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
  async execute(args,exec){
   if(exec.agent!==agent||!current()||session.closed||exec.signal.aborted)throw new Error('前端操作会话已失效');
   if(++calls>24){
    const message='本轮前端操作超过 24 次，请以 partial 交接待提交的组件';
    if(name==='ui_apply')session.applyError=message;
    throw new Error(message);
   }
   session.toolCalls=calls;
   const target={page:'页面布局',main:'主栏',aside:'侧栏',settings:'显示设置',model:'物理场',data:'结果数据',capabilities:'可用组件',evidence:'核查证据'}[args.target];
   const activity={ui_read_skill:'读取展示规范',ui_inspect:'检查'+(target||'页面'),ui_apply:'提交界面调整',ui_wait_for_render:'核对浏览器渲染回执',ui_calculator:args.components?'更新计算器结果组件':'读取计算器契约'};
   if(session.reportActivity)await session.reportActivity(activity[name]);
   if(!current()||session.closed||exec.signal.aborted)throw new Error('前端操作会话已失效');
   if(name==='ui_read_skill'){
    const value=readSkill(args.resource);if(value.resource==='SKILL.md'){skillLoaded=true;session.skillLoaded=true;}return value;
   }
   if(name==='ui_inspect'){
    const value=await call(`/api/tasks/${id}/frontend?target=${encodeURIComponent(args.target)}${args.node?'&node='+encodeURIComponent(args.node):''}`,undefined,exec.signal);
    if(session.request!==undefined&&value.task?.request!==session.request){session.cancel?.();throw new Error('已有新的用户请求，请结束旧前端会话');}
    revisions.add(value.revision);session.observed=true;if(args.target==='page')session.pageObserved=true;return value;
   }
   if(name==='ui_apply'){
    let value;
    try{
     if(!skillLoaded)throw new Error('先 ui_read_skill 读取 '+SKILL.name+' 的 SKILL.md');
     if(typeof args?.expectedRevision!=='string')throw new Error('ui_apply 需要完整 JSON 对象，顶层包含 expectedRevision。检查括号是否闭合，不要包装在 arguments 字符串中。请缩短调用，一次只提交一个组件及其 datasets。');
     if(!revisions.has(args.expectedRevision))throw new Error('必须先 ui_inspect 获取本轮实际状态版本；本轮已读取：'+[...revisions].join(', ')+'；收到：'+String(args.expectedRevision));
     if(!session.pageObserved)throw new Error('先 ui_inspect(target="page") 获取当前实际页面布局、内容与物理场状态');
     if(++mutations>8)throw new Error('本轮前端修改超过 8 次，请以 partial 交接待提交的组件');
     value=await call(`/api/tasks/${id}/frontend`,{...args,...session.request!==undefined?{expectedRequest:session.request}:{}},exec.signal);
    }
    catch(error){session.applyError=String(error.message||error);throw error;}
    if(Object.values(args.datasets||args.update?.ui?.datasets||{}).some(d=>d?.quantity==='csInventory'||d?.caseIdentity)||changesSelectionBinding(args.update?.ui?.root)||changesSelectionBinding(args.update?.ui?.aside)||args.operations?.some(op=>['main','aside'].includes(op.slot)&&changesSelectionBinding(op.props||op.value))){session.checkSelection=true;delete session.selectionCheck;}
    revisions.add(value.revision);session.lastPublished=value;session.mutations=(session.mutations||0)+1;session.applyError=null;session.confirmed=false;return value;
   }
   if(name==='ui_calculator'){
    if(!skillLoaded||!session.pageObserved)throw new Error('先读取前端技能并观察当前页面');
    const path='/api/tasks/'+id+'/calculator',query='?inspect=1&case='+encodeURIComponent(args.case);
    if(args.candidate){
     if(args.components)throw new Error('候选回读与组件修改须分别提交');
     return await call(path+query+'&candidate='+encodeURIComponent(args.candidate),undefined,exec.signal);
    }
    if(args.components){
     if(session.appCase!==args.case||session.appVersion!==args.version)throw new Error('先读取当前应用的契约版本');
     if(++mutations>8)throw new Error('本轮修改超过 8 次');
     await call(path,{action:'components',case:args.case,components:args.components,version:args.version,...session.request!==undefined?{expectedRequest:session.request}:{}},exec.signal);
     session.appMutation=true;session.appConfirmed=false;session.mutations=(session.mutations||0)+1;
    }
    const value=await call(path+query,undefined,exec.signal);
    if(!value.spec)return {available:false,reason:'DSH 尚未为此工况发布应用契约'};
    session.appCase=args.case;session.appVersion=value.spec.version;session.appQuery=path+query;
    return value;
   }
   const timeout=args.timeoutMs??8000;
   if(!Number.isInteger(timeout)||timeout<0||timeout>10000)throw new Error('等待时间必须为 0–10000 毫秒');
   const deadline=Date.now()+timeout,expected=session.lastPublished;
   if(session.appMutation&&!expected){
    let receipt;
    do{
     receipt=(await call(session.appQuery,undefined,exec.signal)).browser;
     if(receipt.version===session.appVersion&&receipt.ready)break;
     if(Date.now()>=deadline)break;
     await sleep(250,exec.signal);
    }while(current());
    session.appConfirmed=receipt.version===session.appVersion&&receipt.ready;
    return {status:session.appConfirmed?'confirmed':'pending',browser:receipt};
   }
   if(args.verifySelection){
    session.requireSelection=true;session.checkSelection=true;
    if(['busy','offline','unavailable','unconfirmed'].includes(session.selectionCheck?.status))delete session.selectionCheck;
   }
   do{
    const page=await call(`/api/tasks/${id}/frontend?target=page`,undefined,exec.signal),browser=page.browser||{};
    const wanted=expected||page;
    session.renderExpected=wanted;
    let status=renderConfirmation(page,wanted);
    if(status==='confirmed')await verifyRenderedSelection(session,page,call,id,exec.signal);
    if(status==='confirmed'&&session.selectionCheck?.status==='failed')status='error';
    else if(status==='confirmed'&&!selectionConfirmed(session))status='selection-unconfirmed';
    if(status!=='pending'||Date.now()>=deadline){revisions.add(page.revision);session.confirmed=status==='confirmed';session.renderStatus=status;return{status,revision:page.revision,presentationVersion:page.presentationVersion,browser,viewer:page.viewer||{},...session.selectionCheck?{selectionCheck:session.selectionCheck}:{}};}
    await sleep(250,exec.signal);
   }while(current());
   throw new Error('前端操作会话已结束');
  },
 });
}
