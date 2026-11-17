import test from 'node:test';
import assert from 'node:assert/strict';
import {TaskSnapshots} from '../assets/task-snapshots.js';
import {NativeHarness} from '../assets/native-harness.js';

test('late SSE snapshots cannot resurrect a completed task after a newer recovery read',()=>{
 const cache=new TaskSnapshots(),running={id:'a',stateVersion:2,status:'running'},done={id:'a',stateVersion:4,status:'completed',presenter:{state:'idle'}};
 assert.equal(cache.accept(running),true);assert.equal(cache.accept(done),true);
 assert.equal(cache.accept({...running,stateVersion:3}),false);assert.equal(cache.accept({id:'a',status:'running'}),false);
 assert.equal(cache.get('a'),done);assert.equal(cache.accept({id:'b',stateVersion:1,status:'running'}),true);
 assert.equal(cache.accept({...done,stateVersion:5,status:'running'}),true); // A real new round is allowed.
});

function harness(){
 const updates=[],h=Object.create(NativeHarness.prototype);
 Object.assign(h,{snapshots:new TaskSnapshots(),current:{id:'a'},selection:1,polling:false,cb:{onMeta:meta=>updates.push(meta)}});
 return{h,updates};
}
test('a missed completion event is recovered without requiring the SSE connection to fail',async t=>{
 const previous=globalThis.document;globalThis.document={hidden:false};t.after(()=>{if(previous===undefined)delete globalThis.document;else globalThis.document=previous;});
 t.mock.method(globalThis,'fetch',async()=>({ok:true,json:async()=>({task:{id:'a',stateVersion:3,status:'completed',presenter:{state:'idle'}}})}));
 const {h,updates}=harness();h.receive({id:'a',stateVersion:2,status:'running'});await h.reconcile();
 assert.equal(h.current.status,'completed');assert.equal(updates.length,2);
 h.receive({id:'a',stateVersion:2,status:'running'});assert.equal(updates.length,2);assert.equal(h.current.status,'completed');
});
test('an in-flight recovery read cannot replace the newly selected task, and network failure preserves activity',async t=>{
 const previous=globalThis.document;globalThis.document={hidden:false};t.after(()=>{if(previous===undefined)delete globalThis.document;else globalThis.document=previous;});
 let finish;t.mock.method(globalThis,'fetch',()=>new Promise(resolve=>finish=resolve));
 const {h,updates}=harness(),pending=h.reconcile();h.selection++;h.current={id:'b',status:'running'};
 finish({ok:true,json:async()=>({task:{id:'a',stateVersion:8,status:'completed'}})});await pending;
 assert.equal(h.current.id,'b');assert.equal(updates.length,0);
 t.mock.method(globalThis,'fetch',async()=>{throw new Error('offline');});await h.reconcile();assert.equal(h.current.status,'running');assert.equal(h.polling,false);
});
