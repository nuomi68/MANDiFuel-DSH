import test from 'node:test';
import assert from 'node:assert/strict';
import {mountProcessEvents} from '../native-plugin/process-events.mjs';
import {conversationEvent} from '../native-plugin/process-conversation.mjs';
import {summarize} from '../native-plugin/process-summary.mjs';
test('science summaries use only the approved provider and reject unsupported completion claims',async()=>{
 let seen,calls=0,answer='核对边界温度输入';
 const llm={async *stream(req){seen=req;calls++;yield {type:'text-delta',text:answer};yield {type:'finish',reason:'stop'};}};
 const window={status:'running',request:'检查边界条件',recent:[],workspace:{}},selection={provider:'deepseek-official',model:'test'};
 const run=(s=selection)=>summarize(llm,s,window,m=>m,new AbortController().signal);
 await assert.rejects(run({provider:'other'}));assert.equal(calls,0);
 assert.equal(await run(),answer);assert.equal(seen.messages.length,1);assert.deepEqual(JSON.parse(seen.messages[0].content[0].text),window);
 answer='已完成求解';await assert.rejects(run());
 window.status='completed';answer='正在运行求解器';await assert.rejects(run());
});
test('short science context excludes reasoning, replacement messages and tool output',()=>{
 const session={eventAt:()=>({data:{name:'Bash'}})};
 const event={type:'assistant/message',surfaceOp:'append',data:{turn:1,step:2,message:{content:[{type:'thinking',text:'hidden'},{type:'text',text:'检查单位'}]}}};
 assert.deepEqual(conversationEvent(session,event),{kind:'assistant-note',text:'检查单位'});
 assert.equal(conversationEvent(session,{...event,surfaceOp:'replace'}),undefined);
 const result={type:'tool/result',surfaceOp:'append',sourceEventSeqs:[12],data:{message:{content:[{type:'tool-result',content:[{type:'text',text:'Exit code: 1\nprivate file'}]}]}}};
 assert.deepEqual(conversationEvent(session,result),{kind:'tool-end',tool:'Bash',failed:true});
});
test('compute children and descendants enter progress; the private UI family cannot',()=>{
 const hooks=new Map(),events=[],ctx={on:(name,fn)=>{const list=hooks.get(name)||[];list.push(fn);hooks.set(name,list);}},emit=(name,...args)=>{for(const fn of hooks.get(name)||[])fn(...args);};
 mountProcessEvents(ctx,{sessions:new Map([['solver','task']]),enqueue:(root,id,event)=>events.push({root,id,...event})});
 const session=(id,parent)=>({id,header:{origin:'subagent',parentSession:parent},title:id});
 const child=session('material','solver'),nested=session('check','material'),uiOwner=session('ui-owner','unbound'),ui=session('ui','ui-owner');
 for(const s of [child,nested,uiOwner,ui])emit('agent/created',{agent:{session:s}});
 emit('session/event',child,{type:'tool/call',data:{name:'Bash',arguments:JSON.stringify({description:'校核材料'})}});
 emit('session/event',child,{type:'turn/end',data:{reason:{kind:'completed'}}});
 emit('session/event',ui,{type:'tool/call',data:{name:'ui_apply'}});
 assert.equal(events.length,4);assert.ok(events.every(e=>e.root==='solver'&&e.id==='task'));assert.deepEqual(events.map(e=>e.sessionId),['material','check','material','material']);assert.equal(events.at(-1).status,'completed');
});
