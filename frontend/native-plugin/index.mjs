import http from 'node:http';
import {randomUUID} from 'node:crypto';
import {mountCalculatorBuilder} from './calculator-builder.mjs';
import {mountPresenter} from './presenter.mjs';
import {mountPresentationRouter} from './presentation-router.mjs';
import {mountProcessEvents} from './process-events.mjs';
import {conversationEvent} from './process-conversation.mjs';
import {mountProcessSummary} from './process-summary.mjs';
export const name='mandifuel-native-workbench';
export const inject=['webServer','connection','workspaceController','sessionController','agents','subagents','agentDefaultModel','llm','tools'];
export async function apply(ctx){
 const backend=new URL(process.env.MANDIFUEL_WORKBENCH_BACKEND),token=process.env.MANDIFUEL_WORKBENCH_TOKEN;
 const sessions=new Map(),queues=new Map(),unmanaged=new Set();
 const workspaceTitle=(title,draft)=> (draft?'计算工作区':title)+' · '+new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3,hour12:false});
 const json=(res,status,data)=>{const body=Buffer.from(JSON.stringify(data));res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':body.length,'Cache-Control':'no-store'});res.end(body);};
 const call=(path,body,signal)=>new Promise((resolve,reject)=>{const bytes=body===undefined?null:Buffer.from(JSON.stringify(body));const request=http.request(new URL(path,backend),{method:bytes?'POST':'GET',signal,headers:{'X-Workbench-Token':token,...(bytes?{'Content-Type':'application/json','Content-Length':bytes.length}:{})}},response=>{let data='';response.setEncoding('utf8');response.on('data',chunk=>data+=chunk);response.on('end',()=>{try{const value=JSON.parse(data);response.statusCode<400?resolve(value):reject(new Error(value.error||'工作台接口失败'));}catch(error){reject(error);}});});request.setTimeout(30000,()=>request.destroy(new Error('展示观察接口超时')));request.on('error',reject);if(bytes)request.write(bytes);request.end();});
 const list=await call('/api/tasks');for(const t of list)if(t.nativeSessionId)sessions.set(t.nativeSessionId,t.id);
 const summaries=process.env.MANDIFUEL_PROGRESS_ENABLED==='0'?null:await mountProcessSummary(ctx,call);
 const enqueue=(session,body)=>{const sid=String(session.id);if(session.header.origin==='subagent'||unmanaged.has(sid))return;const pending=(queues.get(sid)||Promise.resolve()).then(async()=>{let id=sessions.get(sid);if(!id&&session.header.cwd){const adopted=await call('/api/adopt',{cwd:session.header.cwd,sessionId:sid});id=adopted.taskId;if(id)sessions.set(sid,id);else unmanaged.add(sid);}if(id){await call(`/api/tasks/${id}/native-event`,{...body,sessionId:sid});summaries?.notify(sid,body);}}).catch(error=>console.error('Workbench event:',error.message));queues.set(sid,pending);return pending;};
 mountProcessEvents(ctx,{sessions,enqueue:(root,id,body)=>{const pending=(queues.get(root)||Promise.resolve()).then(()=>call(`/api/tasks/${id}/native-event`,body)).catch(error=>console.error('Process observation:',error.message));queues.set(root,pending);}});
 const presenter=process.env.MANDIFUEL_PRESENTATION_ENABLED==='0'?{notify(){}}:mountPresenter(ctx,call,async agent=>{await queues.get(String(agent.id));return sessions.get(String(agent.id));});
 if(process.env.MANDIFUEL_PRESENTATION_ENABLED!=='0')await mountPresentationRouter(ctx,{call,sessions,presenter});
 ctx.on('session/event',(session,event)=>{const sid=String(session.id),data=event.data||{};
  if(event.type==='session/title')enqueue(session,{kind:'title',title:data.title});
  else if(event.type==='turn/end')enqueue(session,{kind:'turn',reason:data.reason?.kind||'error'});
  else if(event.type==='user/message'&&event.surfaceOp==='append'&&data.source?.rpcId&&data.source?.surface!=='presentation')enqueue(session,{kind:'prompt',text:data.content.filter(b=>b.type==='text').map(b=>b.text).join('')});
  else if(event.type==='tool/call'){let args={};try{args=JSON.parse(data.arguments);}catch{}enqueue(session,{kind:'tool',turn:data.turn,time:new Date(event.time).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}),action:args.description||args.path||data.name});}
  else if(session.header.origin!=='subagent'){
   const note=conversationEvent(session,event);
   if(note)enqueue(session,note);
  }
 });
 ctx.on('agent/status',({agent,status})=>{const pending=enqueue(agent.session,{kind:'status',status});if(agent.session.header.origin!=='subagent')Promise.resolve(pending).then(()=>presenter.notify(agent)).catch(()=>{});});
 ctx.on('tools/result',(exec)=>{if(exec.agent?.session.header.origin!=='subagent'&&exec.agent)presenter.notify(exec.agent);});
 const toggleCalculator=mountCalculatorBuilder(ctx,call,list);
 const readBody=async req=>{let bytes=0,chunks=[];for await(const chunk of req){bytes+=chunk.length;if(bytes>262144)throw new Error('任务描述过长');chunks.push(chunk);}return JSON.parse(Buffer.concat(chunks).toString());};
 const handler=async(req,res)=>{
  const url=new URL(req.url,'http://localhost'),relative=url.pathname.slice('/workbench'.length)||'/';
  if(relative==='/'){
   const request={url:'/'+url.search,method:req.method,headers:req.headers};
   const response={writeHead(status,headers={}){const next={...headers};if(status===303){delete next.location;next.Location='/workbench/';}return res.writeHead(status,next);},end(body){return res.end(body);}};
   if(!ctx.connection.authorizeIndex(request,response))return;
  }else{const rejection=ctx.connection.requestRejection(req);if(rejection)return json(res,rejection,{error:'请使用原生 Harness 启动链接登录'});}
  if(url.pathname==='/workbench'){res.writeHead(302,{Location:'/workbench/'+url.search});res.end();return;}
  const opened=req.method==='GET'&&relative.match(/^\/api\/tasks\/(task-[a-f0-9]+)\/stream$/);
  if(opened)void presenter.reviewSaved?.(opened[1]);
  if(['calculator-build-state','process-briefs','process-summary'].includes(relative.split('/').filter(Boolean).at(-1)))return json(res,404,{error:'未找到资源'});
  const build=req.method==='POST'&&relative.match(/^\/api\/tasks\/(task-[a-f0-9]+)\/build-calculator$/);
  if(build){
   if(req.headers['x-workbench-token']!==token)return json(res,403,{error:'工作台会话已过期'});
   try{
    const result=await toggleCalculator(build[1],await readBody(req));
    return json(res,['building','waiting'].includes(result.state)?202:200,result);
   }catch(error){return json(res,400,{error:error.message});}
  }
  if(req.method==='POST'&&(relative==='/api/tasks'||relative==='/api/bootstrap')){
   let prepared;
   try{
    const data=await readBody(req);const draft=relative==='/api/bootstrap';prepared=await call(draft?'/api/draft':'/api/tasks',data);
    if(prepared.task.nativeSessionId){if(!prepared.task.nativeWorkspaceId){const{workspace}=await ctx.workspaceController.create({path:prepared.workspace});prepared=await call(`/api/tasks/${prepared.task.id}/bind`,{sessionId:prepared.task.nativeSessionId,workspaceId:workspace.workspaceId});}if(draft)await ctx.workspaceController.rename({workspaceId:prepared.task.nativeWorkspaceId,title:workspaceTitle(prepared.task.title,true)});return json(res,200,prepared);}
    const {workspace}=await ctx.workspaceController.create({path:prepared.workspace});
    await ctx.workspaceController.rename({workspaceId:workspace.workspaceId,title:workspaceTitle(prepared.task.title,draft)});
    const created=await ctx.sessionController.create({workspaceId:workspace.workspaceId});
    const sid=String(created.sessionId);sessions.set(sid,prepared.task.id);
    await call(`/api/tasks/${prepared.task.id}/bind`,{sessionId:sid,workspaceId:workspace.workspaceId});
    if(!draft){
     await ctx.sessionController.rename({sessionId:created.sessionId,title:prepared.task.title});
     const text='请使用当前准备的 MANDiFuel Skills 和本地资料完成任务。工作区 resources.md 提供资源，按普通终端工作流独立执行输入准备、计算、结果提取与报告，保留实际输入、运行回执和结果。\n\n用户请求：\n'+prepared.prompt;
     await ctx.sessionController.prompt({requestId:randomUUID(),sessionId:created.sessionId,mode:'queue',content:[{type:'text',text}],clientTimeZone:'Asia/Shanghai'},new AbortController().signal);
    }
    return json(res,201,await call(`/api/tasks/${prepared.task.id}`));
   }catch(error){if(prepared)await call(`/api/tasks/${prepared.task.id}/native-event`,{kind:'failure',error:error.message}).catch(()=>{});return json(res,400,{error:error.message});}
  }
  const headers={...req.headers,host:backend.host};delete headers.origin;delete headers.connection;delete headers['accept-encoding'];
  const upstream=http.request(new URL(relative+url.search,backend),{method:req.method,headers},response=>{res.writeHead(response.statusCode,response.headers);response.pipe(res);});
  upstream.on('error',error=>{if(!res.headersSent)json(res,502,{error:'工作台服务未就绪'});else res.destroy(error);});res.on('close',()=>upstream.destroy());req.pipe(upstream);
 };
 ctx.effect(()=>ctx.webServer.register({kind:'prefix',path:'/workbench',handler}));
}
