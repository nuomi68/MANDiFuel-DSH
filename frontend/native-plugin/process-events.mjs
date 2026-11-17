// Read-only lineage tracking for calculation children. UI owners have no bound
// calculation parent, so neither their tools nor their status enter this lane.
export function mountProcessEvents(ctx,{sessions,enqueue}){
 const children=new Map();
 const bind=session=>{
  const sid=String(session.id);if(children.has(sid))return children.get(sid);
  if(session.header.origin!=='subagent')return null;
  const parent=String(session.header.parentSession),ancestor=children.get(parent),id=sessions.get(parent)||ancestor?.id;
  if(!id)return null;
  const value={id,root:ancestor?.root||parent,label:session.title||session.header.title||'计算子任务'};children.set(sid,value);return value;
 };
 const send=(session,payload)=>{const child=bind(session);if(child)enqueue(child.root,child.id,{kind:'subprocess',sessionId:String(session.id),label:child.label,...payload});};
 ctx.on('agent/created',({agent})=>send(agent.session,{status:'running'}));
 ctx.on('agent/status',({agent,status})=>{if(status==='running')send(agent.session,{status:'running'});});
 ctx.on('session/event',(session,event)=>{
  const child=bind(session);if(!child)return;const data=event.data||{};
  if(event.type==='subagent/descriptor'&&data.label)child.label=String(data.label).slice(0,100);
  else if(event.type==='session/title'&&data.title){child.label=String(data.title).slice(0,100);send(session,{});}
  else if(event.type==='turn/end')send(session,{status:data.reason?.kind==='completed'?'completed':data.reason?.kind==='aborted'?'stopped':'failed'});
  else if(event.type==='tool/call'){
   let args={};try{args=JSON.parse(data.arguments);}catch{}
   send(session,{status:'running',action:args.description||data.name||'执行子过程'});
  }
 });
 return{children};
}
