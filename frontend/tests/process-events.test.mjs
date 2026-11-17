import test from 'node:test';
import assert from 'node:assert/strict';
import {mountProcessEvents} from '../native-plugin/process-events.mjs';
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
