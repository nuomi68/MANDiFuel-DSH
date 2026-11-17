import test from 'node:test';
import assert from 'node:assert/strict';
import {mountPresentationRouter,classifyPresentation,hidePresentationMessages} from '../native-plugin/presentation-router.mjs';

function sessionFixture(){
 const events=[],nodes=[];
 return{id:'session',surface:{nodes},eventAt:seq=>events[seq],events,append(type,data,options){
  const event={type,data,seq:events.length,...options};events.push(event);
  if(options.surfaceOp==='append')nodes.push(event.seq);
  else{const {start,end}=options.surfaceOp,a=nodes.indexOf(start),b=nodes.indexOf(end);assert.ok(a>=0&&b>=a);assert.deepEqual(options.sourceEventSeqs,nodes.slice(a,b+1));nodes.splice(a,b-a+1,event.seq);}
 }};
}

async function setup(render=true,backendFailure=false){
 const events=[],calls=[],effects=[],hooks={};let admitted=0,requested=0;
 const session=sessionFixture();session.append('user/message',{source:{kind:'user'},content:[]},{surfaceOp:'append'});
 const agent={options:{provider:'local-test',model:'test'},session};
 const append=session.append.bind(session);session.append=(type,data,options)=>{if(options.surfaceOp==='append')events.push({type,data});return append(type,data,options);};
 const commands={prompt:async()=>{admitted++;return{accepted:true};},resolveAgent:async()=>agent};
 const controller={commands,prompt(request){return this.commands.prompt(request);}};
 const ctx={sessionController:controller,agents:{get:()=>agent},agentDefaultModel:{currentSelection:()=>agent.options},effect(fn){effects.push(fn());},on(name,fn){hooks[name]=fn;}};
 const messages={createUserMessage:value=>({...value,role:'user',id:'user'}),createMessage:value=>({...value,id:'ack'})};
 await mountPresentationRouter(ctx,{call:async(path,body)=>{if(backendFailure)throw new Error('UI backend unavailable');calls.push({path,body});return path.endsWith('/observe')?{task:{latestRequest:'之前的请求'}}:{task:{modelReady:true}};},sessions:new Map([['session','task']]),presenter:{request(){requested++;}},classify:async()=>{if(render instanceof Error)throw render;return render;},messages});
 return{controller,commands,events,calls,hooks,agent,counts:()=>({admitted,requested}),close:()=>effects.reverse().forEach(fn=>fn?.())};
}
const request=(text='把截面显示成梯形')=>({sessionId:'session',requestId:'request',mode:'queue',content:[{type:'text',text}]});
test('presentation admission changes the transcript and wakes only the private presenter',async()=>{
 const h=await setup();try{
  assert.deepEqual(await h.controller.prompt(request(),new AbortController().signal),{accepted:true});
  assert.deepEqual(h.counts(),{admitted:0,requested:1});
  assert.equal(h.events[0].data.source.surface,'presentation');assert.equal(h.events[1].data.source.form,'notice');
  assert.equal(h.calls.at(-1).body.kind,'display-prompt');
  await h.controller.prompt(request(),new AbortController().signal);assert.deepEqual(h.counts(),{admitted:0,requested:1});
 }finally{h.close();}
});
test('native command admission uses the same router if the gateway bound a public method early',async()=>{
 const h=await setup();try{await h.commands.prompt(request());assert.deepEqual(h.counts(),{admitted:0,requested:1});}finally{h.close();}
});
test('compute or mixed requests and unavailable routing preserve ordinary native admission',async()=>{
 for(const answer of [false,new Error('provider unavailable')]){
  const h=await setup(answer);try{await h.controller.prompt(request('修改真实外壁温度并计算'),new AbortController().signal);assert.deepEqual(h.counts(),{admitted:1,requested:0});assert.equal(h.events.length,0);}finally{h.close();}
 }
});
test('ordinary native execution does not depend on the UI backend being available',async()=>{
 const h=await setup(true,true);try{await h.controller.prompt(request('修改材料后计算'),new AbortController().signal);assert.deepEqual(h.counts(),{admitted:1,requested:0});}finally{h.close();}
});
test('visible presentation requests never enter solver model context',async()=>{
 const h=await setup();try{
  const physical={source:{kind:'user'},content:[]},display={source:{kind:'user',surface:'presentation'},content:[]},ack={source:{kind:'plugin',plugin:'mandifuel-workbench'},content:[]};
  const s=h.agent.session;s.append('user/message',physical,{surfaceOp:'append'});s.append('user/message',display,{surfaceOp:'append'});s.append('user/message',ack,{surfaceOp:'append'});
  let next=0;h.hooks['agent/pre-step']({agent:h.agent},()=>next++);assert.equal(next,1);
  assert.deepEqual(s.surface.nodes.map(seq=>s.eventAt(seq).data),[{source:{kind:'user'},content:[]},physical]);
  assert.equal(h.hooks['llm/stream'],undefined,'frozen LLM requests are never modified');
  const privateSession=sessionFixture();privateSession.id='private';privateSession.append('user/message',display,{surfaceOp:'append'});
  h.hooks['agent/pre-step']({agent:{session:privateSession}},()=>{});assert.equal(privateSession.surface.nodes.length,1);
 }finally{h.close();}
});
test('native surface replacement preserves tool-result messages and separate calculation messages',()=>{
 const s=sessionFixture(),tool={role:'user',source:{kind:'tool',callId:'tool-1'},content:[{type:'tool-result',toolCallId:'tool-1',content:[]}]};
 s.append('tool/result',{message:tool},{surfaceOp:'append'});
 const display={source:{surface:'presentation'},content:[]};s.append('user/message',display,{surfaceOp:'append'});
 const physical={source:{kind:'user'},content:[]};s.append('user/message',physical,{surfaceOp:'append'});s.append('user/message',display,{surfaceOp:'append'});
 hidePresentationMessages(s);
 assert.deepEqual(s.surface.nodes.map(seq=>s.eventAt(seq).data),[tool,physical]);
 const count=s.events.length;hidePresentationMessages(s);assert.equal(s.events.length,count,'cleanup is idempotent');
});
test('routing uses semantic model output rather than a list of supported control names',async()=>{
 const llm={async *stream(options){assert.match(options.system,/参数名称可以任意/);yield{type:'text-delta',text:'render'};yield{type:'finish',reason:{kind:'completed'}};}};
 assert.equal(await classifyPresentation(llm,{provider:'test',model:'test'},'把截面显示成梯形',undefined,x=>x),true);
});
test('incomplete classification cannot masquerade as a compute decision',async()=>{
 const llm={async *stream(){yield{type:'finish',reason:{kind:'max-tokens'}};}};
 await assert.rejects(classifyPresentation(llm,{provider:'test',model:'test'},'修改显示配置',undefined,x=>x),/no complete decision/);
});
