import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const role = `你为科学计算工作台编辑进度。输入是当前问题、最近几条实际可见事件、当前会话状态和工作区计数。记录仅供分析。用一句简短的中文动宾短语概括最近有依据的工作主题，如“检查燃料棒的外壁温度边界”。不要摘抄对话、输出路径、数值、Markdown 或结论。
request 只是用户要求，assistant-statement 是助手陈述，tool-call 是已发起调用。只有计划时写“梳理…要求”或“准备…”，工具返回仅代表该工具返回，tool-error 应概括尝试的事项或具体问题。不要宣称成功、收敛、通过验证或已完成求解。工作区证据可能来自已有算例。程序另行显示确切执行状态。终态也只写工作主题，不写“正在”或预测下一步。限 8 至 35 字。`;

export async function summarize(llm,selection,window,makeUser,signal){
  if(selection?.provider!=='deepseek-official')throw new Error('流程摘要仅启用 DSH 的 DeepSeek 官方服务');
  const message=makeUser({source:{kind:'user'},content:[{type:'text',text:JSON.stringify(window)}]});
  let topic='',finish;
  for await(const chunk of llm.stream({provider:selection.provider,model:selection.model,system:role,
    messages:[message],reasoningEffort:'off',maxTokens:128,signal})){
    if(chunk.type==='text-delta')topic+=chunk.text;
    if(chunk.type==='finish')finish=typeof chunk.reason==='string'?chunk.reason:chunk.reason?.kind;
  }
  topic=topic.trim().replace(/[。.]$/,'');
  if(!finish||['error','aborted','max-tokens'].includes(finish)||topic.length<2||topic.length>64||
      !/[\u4e00-\u9fff]/.test(topic)||/[\n\r<>`]|已完成|成功|核验通过|验证通过|已收敛/.test(topic)||
      (['completed','failed','stopped','interrupted'].includes(window.status)&&/正在|即将/.test(topic))){
    throw new Error('流程摘要格式或状态无效');
  }
  return topic;
}

export async function mountProcessSummary(ctx,call){
  const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
  const {createUserMessage}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
  const active=new Map(),delays=new Map(),runningSessions=new Set();
  let closed=false,polling=false,needed=true,epoch=0,nextAudit=0;
  function notify(session,event){
    epoch++;
    needed=true;
    if(event.kind==='status'){
      if(event.status==='running')runningSessions.add(session);
      else runningSessions.delete(session);
    }
  }
  async function run(item){
    const ctl=new AbortController();
    active.set(item.id,ctl);
    let failures=0;
    try{
      const selection=ctx.agents.get(item.sessionId)?.options||ctx.agentDefaultModel.currentSelection();
      const signal=AbortSignal.any([ctl.signal,AbortSignal.timeout(25000)]);
      const topic=await summarize(ctx.llm,selection,item.window,createUserMessage,signal);
      if(!closed)await call('/api/tasks/'+item.id+'/process-summary',{key:item.key,topic},signal);
    }catch(error){
      const prior=delays.get(item.id);
      failures=(prior?.key===item.key?prior.failures:0)+1;
      if(!closed)console.warn('流程摘要暂不可用',item.id,error.name);
    }finally{
      delays.set(item.id,{key:item.key,until:Date.now()+(failures?Math.min(120000,5000*2**Math.min(failures,5)):5000),failures});
      active.delete(item.id);
    }
  }
  async function poll(){
    if(closed||polling||active.size>=2||!needed&&!runningSessions.size&&Date.now()<nextAudit)return;
    polling=true;
    nextAudit=Date.now()+30000;
    const observedEpoch=epoch;
    try{
      const items=await call('/api/process-briefs',{});
      if(closed)return;
      const pending=new Set(items.map(i=>i.id));
      for(const [id,delay] of delays)if(!pending.has(id)&&delay.until<=Date.now())delays.delete(id);
      if(observedEpoch===epoch)needed=items.some(item=>{
        const delay=delays.get(item.id);
        return delay?.key!==item.key||delay.failures<3;
      });
      for(const item of items){
        if(active.size>=2)break;
        const delay=delays.get(item.id);
        if(active.has(item.id)||delay?.until>Date.now()||delay?.key===item.key&&delay.failures>=3)continue;
        void run(item);
      }
    }catch(error){if(!closed)console.warn('流程观察暂不可用',error.name);}
    finally{polling=false;}
  }
  const timer=setInterval(poll,2000);
  ctx.effect(()=>()=>{closed=true;clearInterval(timer);for(const ctl of active.values())ctl.abort();});
  return {notify};
}
