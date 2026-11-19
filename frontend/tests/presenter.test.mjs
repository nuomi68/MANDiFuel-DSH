import test from 'node:test';
import assert from 'node:assert/strict';
import {mountPresenter,publishUpdate} from '../native-plugin/presenter.mjs';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('a rejected optional chart cannot discard a valid mechanical field export',async()=>{
 const committed=[];const update={exports:[{id:'mechanics',caseRoot:'repaired',fields:['epsilon:xx']}],defaultView:'mechanics',viewState:{view:'mechanics',field:'epsilon_xx'},ui:{root:{id:'badChart',type:'lineChart',source:{}}},progress:{summary:'展示完成'}};
 await assert.rejects(publishUpdate(async(path,body)=>{if(body.ui)throw new Error('badChart: source belongs inside series');committed.push(body);return{modelReady:true};},'task',update),/badChart/);
 assert.equal(committed.length,1);assert.deepEqual(committed[0].exports,update.exports);assert.equal(committed[0].viewState.field,'epsilon_xx');assert.equal(committed[0].progress,undefined);
});
async function until(check){for(let i=0;i<100;i++){if(check())return;await delay(10);}throw new Error('等待展示子任务超时');}
function setup(start,call,options){const disposers=[];const ctx={agentDefaultModel:{currentSelection:()=>({provider:'test-provider',model:'test-model'})},agents:{create:async request=>{assert.equal(request.agentOptions.provider,'test-provider');assert.equal(request.agentOptions.model,'test-model');return{agent:{id:'presentation-owner',session:{header:{origin:'subagent'}}},dispose:async()=>{}};}},subagents:{start},on(){},effect(factory){disposers.push(factory());}};const agent={id:'parent',status:'running',session:{header:{origin:'interactive'}}};const presenter=mountPresenter(ctx,call,async()=> 'task',options);return{agent,presenter,close:async()=>{for(const d of disposers)await d();}};}
function facts(revision='one',status='running'){return{revision,stage:'prepare',cases:[],views:[],task:{status},summary:'正在准备'};}

test('an explicit request arriving during observation discards the old snapshot before spawning',async()=>{
 let release,starts=0,disposed=0,observations=0;
 const h=setup(async()=>{starts++;return{id:'latest',result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async path=>path.endsWith('/observe')?++observations===1?new Promise(resolve=>release=resolve):facts('new'):{});
 try{h.presenter.request('task');await until(()=>!!release);h.presenter.request('task');release(facts('old'));await delay(20);assert.equal(starts,0);h.presenter.notify(h.agent);await until(()=>disposed===1);assert.equal(starts,1);}finally{await h.close();}
});

test('a newer display request cancels the old child without publishing a retry error',async()=>{
 let starts=0,disposed=0,signal;const states=[],commits=[];
 const h=setup(async(_provider,request)=>{starts++;if(starts===1){signal=request.signal;return{id:'old',result:new Promise(resolve=>signal.addEventListener('abort',()=>resolve({stopReason:'completed',structured:{update:{rendering:{palette:'gray'}}}}),{once:true})),dispose:async()=>disposed++};}return{id:'new',result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return facts();if(path.endsWith('/presenter'))states.push(body);if(path.endsWith('/present'))commits.push(body);return{};});
 try{h.presenter.request('task');await until(()=>!!signal);h.presenter.request('task');await until(()=>disposed===1);assert(signal.aborted);assert(!states.some(s=>s.retryAt||s.state==='error'));assert.equal(commits.length,0);h.presenter.notify(h.agent);await until(()=>disposed===2);assert.equal(starts,2);}finally{await h.close();}
});

test('coalesces observations and does not mutate immutable late child output',async()=>{
 let release,starts=0,disposed=0,current=facts(),published;
 const original=Object.freeze({progress:Object.freeze({summary:'旧进度'}),exports:Object.freeze([]),controls:Object.freeze([])});
 const h=setup(async()=>{starts++;return{id:'child',result:new Promise(r=>release=r),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present')){published=body;return{};}return{};});
 try{h.presenter.notify(h.agent);await until(()=>starts===1);for(let i=0;i<10;i++)h.presenter.notify(h.agent);assert.equal(starts,1);current=facts('two');release({stopReason:'completed',structured:{update:original}});await until(()=>disposed===1);assert(!('progress' in published));assert(!('exports' in published));assert.equal(original.progress.summary,'旧进度');}
 finally{await h.close();}
});

test('validation failure is sent back to the next native presentation child',async t=>{
 let clock=100000,starts=0,disposed=0,feedback=false,finished=false;t.mock.method(Date,'now',()=>clock);
 const h=setup(async(_provider,request)=>{starts++;feedback=request.prompt[0].text.includes('模型半径不匹配')&&request.prompt[0].text.includes('"rejectedUpdate":{"invalid":true}');return{id:'child-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:starts===1?{invalid:true}:{controls:[]}}}),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return facts();if(path.endsWith('/present')){if(body.invalid)throw new Error('模型半径不匹配');finished=true;return{};}return{};});
 try{h.presenter.notify(h.agent);await until(()=>disposed===1);clock+=13000;h.presenter.notify(h.agent);await until(()=>disposed===2);assert(feedback);assert(finished);assert.equal(starts,2);}
 finally{await h.close();}
});

test('stopping the main task cancels a pending presentation child',async()=>{
 let signal,disposed=0,current=facts();
 const h=setup(async(_provider,request)=>{signal=request.signal;return{id:'child',result:new Promise(resolve=>signal.addEventListener('abort',()=>resolve({stopReason:'aborted'}),{once:true})),dispose:async()=>disposed++};},async path=>path.endsWith('/observe')?current:{});
 try{h.presenter.notify(h.agent);await until(()=>!!signal);current=facts('stopped','stopped');h.agent.status='idle';h.presenter.notify(h.agent);await until(()=>signal.aborted&&disposed===1);}
 finally{await h.close();}
});

test('explicit display requirements accompany the child completion claim',async()=>{
 let published,disposed=0;
 const current={...facts(),deliveryRequirements:{reconstruction:'axisymmetric-revolve',angle:270,extrema:true}};
 const h=setup(async()=>({id:'child',result:Promise.resolve({stopReason:'completed',structured:{update:{progress:{summary:'完成'}}}}),dispose:async()=>disposed++}),async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))published=body;return{};});
 try{h.presenter.notify(h.agent);await until(()=>disposed===1);assert.deepEqual(published.deliveryRequirements,current.deliveryRequirements);}
 finally{await h.close();}
});

test('late styling from an older instruction cannot override a new user request',async()=>{
 let release,published,disposed=0,current={...facts(),task:{status:'running',latestRequest:'改成灰色'}};
 const h=setup(async()=>({id:'child',result:new Promise(resolve=>release=resolve),dispose:async()=>disposed++}),async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))published=body;return{};});
 try{h.presenter.notify(h.agent);await until(()=>!!release);current={...facts('new'),task:{status:'running',latestRequest:'把 X 放大两倍'}};release({stopReason:'completed',structured:{update:{rendering:{palette:'gray'},controls:[{id:'palette'}],viewState:{yaw:90},ui:{version:1,root:{id:'old',type:'text',text:'旧布局'}}}}});await until(()=>disposed===1);assert(!('rendering' in published));assert(!('controls' in published));assert(!('viewState' in published));assert(!('ui' in published));}
 finally{await h.close();}
});

test('a completed solver still receives bounded automatic repairs from actual browser UI feedback',async()=>{
 let starts=0,disposed=0,current={...facts('initial','completed'),task:{status:'completed',latestRequest:'展示曲线'},uiState:{}},publishedRevision=0,feedback=false,lastState;
 const h=setup(async(_provider,request)=>{starts++;if(starts===2)feedback=request.prompt[0].text.includes('浏览器实际渲染反馈')&&request.prompt[0].text.includes('坐标列不存在');return{id:'ui-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:{ui:{version:1,root:{id:'plot',type:'text',text:'说明'}}}}}),dispose:async()=>disposed++};},async(path,body)=>{
  if(path.endsWith('/observe'))return current;
  if(path.endsWith('/present'))return{uiRevision:++publishedRevision};
  if(path.endsWith('/presenter'))lastState=body;
  return{};
 });
 try{
  h.presenter.notify(h.agent);await until(()=>disposed===1);assert.equal(lastState.state,'waiting');
  current={...current,revision:'browser-error',uiState:{revision:1,panels:['plot'],errors:[{id:'plot',message:'坐标列不存在'}]}};h.presenter.notify(h.agent);await until(()=>disposed===2);assert(feedback);assert.equal(starts,2);
  current={...current,revision:'repaired',uiState:{revision:2,panels:['plot'],errors:[]}};h.presenter.notify(h.agent);await until(()=>lastState.state==='idle');assert.equal(starts,2);assert.equal(lastState.message,'界面已显示');
 }finally{await h.close();}
});

test('persistent UI errors stop after two repairs instead of spawning an unbounded loop',async()=>{
 let starts=0,disposed=0,revision=0,lastState,current={...facts('initial','completed'),task:{status:'completed',latestRequest:'展示面板'},uiState:{}};
 const h=setup(async()=>{starts++;return{id:'ui-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:{ui:{version:1,root:{id:'plot',type:'text',text:'说明'}}}}}),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))return{uiRevision:++revision};if(path.endsWith('/presenter'))lastState=body;return{};});
 try{
  h.presenter.notify(h.agent);await until(()=>disposed===1);
  for(let i=1;i<=2;i++){current={...current,revision:'error-'+i,uiState:{revision:i,panels:['plot'],errors:[{id:'plot',message:'仍未满足渲染条件'}]}};h.presenter.notify(h.agent);await until(()=>disposed===i+1);}
  current={...current,revision:'error-3',uiState:{revision:3,panels:['plot'],errors:[{id:'plot',message:'仍未满足渲染条件'}]}};h.presenter.notify(h.agent);await until(()=>lastState.state==='error');assert.equal(starts,3);h.presenter.notify(h.agent);await delay(25);assert.equal(starts,3);
 }finally{await h.close();}
});

test('a view instruction waits for its own browser revision and repairs renderer failures',async()=>{
 let starts=0,disposed=0,revision=0,lastState,feedback=false,current={...facts('initial','completed'),task:{status:'completed',latestRequest:'XY 正视'},viewerState:{revision:0,cameraView:'3d'}};
 const h=setup(async(_provider,request)=>{starts++;if(starts===2)feedback=request.prompt[0].text.includes('模型截面不可用');return{id:'camera-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:{viewState:{cameraView:'xy'}}}}),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))return{modelReady:true,viewStateRevision:++revision};if(path.endsWith('/presenter'))lastState=body;return{};});
 try{
  h.presenter.notify(h.agent);await until(()=>disposed===1);assert.equal(lastState.state,'waiting');h.presenter.notify(h.agent);await delay(20);assert.equal(starts,1);assert.equal(lastState.state,'waiting');
  current={...current,revision:'render-error',viewerState:{revision:1,cameraView:'xy',rendererError:'模型截面不可用'}};h.presenter.notify(h.agent);await until(()=>disposed===2);assert(feedback);
  current={...current,revision:'rendered',viewerState:{revision:2,cameraView:'xy',rendererError:''}};h.presenter.notify(h.agent);await until(()=>lastState.state==='idle');assert.equal(starts,2);
 }finally{await h.close();}
});


test('browser acknowledgement cannot swallow saved-output changes received while waiting',async()=>{
 let starts=0,disposed=0,current={...facts('first'),dataRevision:'save-1',task:{status:'running',latestRequest:'展示已有数据'},uiState:{}};
 const h=setup(async()=>{starts++;return{id:'ui-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:{ui:{version:1,root:{id:'plot',type:'text',text:'当前结果'}}}}}),dispose:async()=>disposed++};},async(path)=>path.endsWith('/observe')?current:path.endsWith('/present')?{uiRevision:starts}:{});
 try{
  h.presenter.notify(h.agent);await until(()=>disposed===1);
  current={...current,revision:'second',dataRevision:'save-2',uiState:{revision:1,panels:['plot'],errors:[]}};
  h.presenter.notify(h.agent);await until(()=>disposed===2);assert.equal(starts,2);
 }finally{await h.close();}
});

test('stable local file changes wake a settled presentation child without any main-agent notification',async t=>{
 let clock=100000,tick,starts=0,disposed=0,current={...facts('one','completed'),dataRevision:'files-1',task:{status:'completed',latestRequest:'展示研究'}};
 t.mock.method(Date,'now',()=>clock);t.mock.method(globalThis,'setInterval',fn=>{tick=fn;return 1;});t.mock.method(globalThis,'clearInterval',()=>{});
 const h=setup(async()=>{starts++;return{id:'file-'+starts,result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async path=>path.endsWith('/observe')?current:{});
 try{
  h.agent.status='idle';h.presenter.notify(h.agent);await until(()=>disposed===1);tick();await delay(20);assert.equal(starts,1);
  clock+=13000;current={...current,revision:'two',dataRevision:'files-2',workspaceChanges:{revision:2,events:[{kind:'case',caseRoot:'cases/a',latestTime:'1'}]}};
  tick();await until(()=>disposed===2);assert.equal(starts,2);tick();await delay(20);assert.equal(starts,2);
 }finally{await h.close();}
});


test('presentation children belong to a private owner and UI failure does not mutate the solver',async()=>{
 let parent,disposed=0;const h=setup(async(_provider,request)=>{parent=request.parent;return{id:'ui',result:Promise.resolve({stopReason:'error',diagnostic:'UI provider unavailable'}),dispose:async()=>disposed++};},async path=>path.endsWith('/observe')?facts():{});
 try{h.presenter.notify(h.agent);await until(()=>disposed===1);assert.notEqual(parent,h.agent);assert.equal(parent.id,'presentation-owner');assert.equal(h.agent.status,'running');assert.equal(h.agent.session.header.origin,'interactive');}finally{await h.close();}
});


test('workspace file notifications start a private worker even when no solver agent is live',async t=>{
 let tick,revision=1,starts=0,disposed=0;
 t.mock.method(globalThis,'setInterval',fn=>{tick=fn;return 1;});t.mock.method(globalThis,'clearInterval',()=>{});
 const h=setup(async(_provider,request)=>{assert.equal(request.parent.id,'presentation-owner');starts++;return{id:'independent',result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async path=>path==='/api/tasks'?[{id:'task',workspaceRevision:revision,draft:false}]:path.endsWith('/observe')?{...facts('files-'+revision,'completed'),dataRevision:'files-'+revision}:{});
 try{await delay(20);assert.equal(starts,0);revision=2;tick();await until(()=>disposed===1);assert.equal(starts,1);assert.equal(h.agent.status,'running');}finally{await h.close();}
});


test('a late presentation result cannot overwrite a newer explicit chart layout',async()=>{
 let release,published,disposed=0,current={...facts(),presentation:{uiRevision:1}};
 const h=setup(async()=>({id:'old-chart',result:new Promise(resolve=>release=resolve),dispose:async()=>disposed++}),async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))published=body;return{};});
 try{h.presenter.notify(h.agent);await until(()=>!!release);current={...current,presentation:{uiRevision:2}};release({stopReason:'completed',structured:{update:{ui:{version:1,root:{id:'old',type:'text',text:'旧图'}}}}});await until(()=>disposed===1);assert(!('ui' in published));}finally{await h.close();}
});

test('already completed files discovered on startup wake a worker without a main agent',async t=>{
 let starts=0,disposed=0;t.mock.method(globalThis,'setInterval',()=>1);t.mock.method(globalThis,'clearInterval',()=>{});
 const h=setup(async()=>{starts++;return{id:'startup',result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async path=>path==='/api/tasks'?[{id:'task',workspaceRevision:4,status:'completed',draft:false}]:path.endsWith('/observe')?{...facts('existing','completed'),dataRevision:'existing'}:{});
 try{await until(()=>disposed===1);assert.equal(starts,1);}finally{await h.close();}
});

test('reactivating a confirmed historical task does not regenerate the same UI, but an explicit request still runs',async()=>{
 let starts=0,disposed=0;const current={...facts('stable','completed'),dataRevision:'saved-results',presenter:{state:'idle',dataRevision:'saved-results'},uiState:{errors:[]}};
 const h=setup(async()=>{starts++;return{id:'new-request',result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>disposed++};},async path=>path.endsWith('/observe')?current:{});
 try{h.presenter.notify(h.agent);await delay(30);assert.equal(starts,0);h.presenter.request('task');await until(()=>disposed===1);assert.equal(starts,1);}finally{await h.close();}
});

test('a hanging presentation cannot block a different task and times out without touching the solver',async t=>{
 let starts=[],signal,tick,first=true;const states={archive:{...facts('old','completed'),dataRevision:'old'},current:{...facts('new','completed'),dataRevision:'new'}};
 t.mock.method(globalThis,'setInterval',fn=>{tick=fn;return 1;});t.mock.method(globalThis,'clearInterval',()=>{});
 const h=setup(async(_provider,request)=>{const id=request.prompt[0].text.includes('"dataRevision":"new"')?'current':'archive';starts.push(id);if(id==='archive'){signal=request.signal;return{id,result:new Promise(()=>{}),dispose:async()=>{}};}return{id,result:Promise.resolve({stopReason:'completed',structured:{update:{}}}),dispose:async()=>{}};},async path=>{if(path==='/api/tasks'){const tasks=first?[{id:'archive',workspaceRevision:1,status:'completed'}]:[{id:'archive',workspaceRevision:1,status:'completed'},{id:'current',workspaceRevision:1,status:'completed'}];first=false;return tasks;}if(path.endsWith('/observe'))return states[path.split('/')[3]];return{};},{timeoutMs:60,maxWorkers:2});
 try{await until(()=>!!signal);tick();await until(()=>starts.includes('current'));await until(()=>signal.aborted);assert.deepEqual(starts,['archive','current']);assert.equal(h.agent.status,'running');}finally{await h.close();}
});

test('a browser acknowledgement arriving after the deadline still clears the warning without regenerating UI',async t=>{
 let now=100000,starts=0,disposed=0,lastState,current={...facts('initial','completed'),dataRevision:'stable',uiState:{}};t.mock.method(Date,'now',()=>now);
 const h=setup(async()=>{starts++;return{id:'late-browser',result:Promise.resolve({stopReason:'completed',structured:{update:{ui:{version:1,root:{id:'note',type:'text',text:'ready'}}}}}),dispose:async()=>disposed++};},async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/present'))return{uiRevision:1};if(path.endsWith('/presenter'))lastState=body;return{};});
 try{h.presenter.notify(h.agent);await until(()=>disposed===1);now+=31000;h.presenter.notify(h.agent);await until(()=>lastState.state==='warning');current={...current,uiState:{revision:1,panels:['note'],errors:[]}};h.presenter.notify(h.agent);await until(()=>lastState.state==='idle');assert.equal(starts,1);}finally{await h.close();}
});

test('the private operator receives the current rendered page before planning and observes it again',async()=>{
 const hooks=new Map(),disposers=[],definitions=new Map();let captured,finished=false;
 const page={revision:'actual',task:{request:'调整布局'},presentationVersion:3,uiRevision:2,viewStateRevision:0,browser:{connected:true,ready:true,presentationVersion:3,revision:2,errors:[],nodes:[{id:'chart',activeTab:'stress'}],model:{visible:true,ready:true,kind:'fields'}}};
 const ctx={tools:{},agentDefaultModel:{currentSelection:()=>({provider:'local',model:'test'})},agents:{create:async()=>({agent:{id:'owner'},dispose:async()=>{}})},on:(name,fn)=>hooks.set(name,fn),effect:factory=>disposers.push(factory()),subagents:{start:async(_provider,request)=>{
  captured=JSON.parse(request.prompt[0].text.split('\n').slice(1).join('\n'));
  const child={ctx:{tools:{register:d=>definitions.set(d.name,d)}},session:{header:{origin:'subagent',parentSession:'owner'}}};hooks.get('agent/created')({agent:child});
  for(const [name,args]of [['ui_read_skill',{}],['ui_inspect',{target:'page'}],['ui_wait_for_render',{timeoutMs:0}]])await definitions.get(name).execute(args,{agent:child,signal:request.signal});
  return{id:'private',result:Promise.resolve({stopReason:'completed',structured:{status:'unchanged',summary:'已有展示符合要求',revision:'actual'}}),dispose:async()=>{finished=true;}};
 }}};
 const call=async path=>path.endsWith('/observe')?{...facts('data','completed'),dataRevision:'data',task:{status:'completed',latestRequest:'调整布局'}}:path.includes('/frontend')?structuredClone(page):{};
 const p=mountPresenter(ctx,call,async()=> 'task');
 try{p.request('task');await until(()=>finished);assert.deepEqual(captured.currentPage,page);assert.deepEqual([...definitions.keys()].sort(),['ui_apply','ui_inspect','ui_read_skill','ui_wait_for_render']);}
 finally{for(const dispose of disposers)await dispose();}
});

test('finite retry backoff remains queued and only the exhausted attempt reports a terminal error',async t=>{
 let now=100000,disposed=0,lastState;const published=[];t.mock.method(Date,'now',()=>now);
 const h=setup(async()=>({id:'retry',result:Promise.reject(new Error('temporary')),dispose:async()=>disposed++}),async(path,body)=>{
  if(path.endsWith('/observe'))return facts('unchanged','completed');if(path.endsWith('/presenter')){lastState=body;published.push(body);}return{};
 });
 try{
  h.presenter.notify(h.agent);await until(()=>disposed===1);assert.equal(lastState.state,'queued');assert.equal(lastState.retryAt,now+5000);
  now+=6000;h.presenter.notify(h.agent);await until(()=>disposed===2);assert.equal(lastState.state,'queued');
  now+=11000;h.presenter.notify(h.agent);await until(()=>disposed===3);assert.equal(lastState.state,'error');
  assert.equal(published.filter(s=>s.state==='error').length,1);assert.equal(h.agent.status,'running');
 }finally{await h.close();}
});

test('new results received during a child keep the next update queued through coalescing',async t=>{
 let now=100000,release,disposed=0,lastState,current={...facts('one','completed'),dataRevision:'one'};t.mock.method(Date,'now',()=>now);
 const h=setup(async()=>({id:'child',result:new Promise(resolve=>release=resolve),dispose:async()=>disposed++}),async(path,body)=>{if(path.endsWith('/observe'))return current;if(path.endsWith('/presenter'))lastState=body;return{};});
 try{
  h.presenter.notify(h.agent);await until(()=>!!release);current={...facts('two','completed'),dataRevision:'two'};
  release({stopReason:'completed',structured:{update:{}}});await until(()=>disposed===1);assert.equal(lastState.state,'queued');
  h.presenter.notify(h.agent);await delay(20);assert.equal(lastState.state,'queued');assert.equal(disposed,1);
  now+=13000;h.presenter.notify(h.agent);await until(()=>lastState.state==='running');release({stopReason:'completed',structured:{update:{}}});await until(()=>disposed===2);assert.equal(lastState.state,'idle');
 }finally{await h.close();}
});

test('an unchanged claim without mutation or render-wait cannot finish before the model is actually ready',async()=>{
 const hooks=new Map(),disposers=[],definitions=new Map();let finished=false,lastState,starts=0;
 const page={revision:'actual',task:{request:'展示物理场'},presentationVersion:3,uiRevision:2,viewStateRevision:0,modelRequirement:{required:true,kind:'fields'},browser:{connected:true,ready:true,presentationVersion:3,revision:2,errors:[],model:{visible:true,ready:false,kind:'pending'}}};
 const ctx={tools:{},agentDefaultModel:{currentSelection:()=>({provider:'local',model:'test'})},agents:{create:async()=>({agent:{id:'owner'},dispose:async()=>{}})},on:(name,fn)=>hooks.set(name,fn),effect:factory=>disposers.push(factory()),subagents:{start:async(_provider,request)=>{
  starts++;const child={ctx:{tools:{register:d=>definitions.set(d.name,d)}},session:{header:{origin:'subagent',parentSession:'owner'}}};hooks.get('agent/created')({agent:child});
  for(const [name,args]of [['ui_read_skill',{}],['ui_inspect',{target:'page'}]])await definitions.get(name).execute(args,{agent:child,signal:request.signal});
  return{id:'private',result:Promise.resolve({stopReason:'completed',structured:{status:'unchanged',summary:'已有物理场'}}),dispose:async()=>{finished=true;}};
 }}};
 const call=async(path,body)=>{if(path.endsWith('/observe'))return{...facts('data','completed'),dataRevision:'data',task:{status:'completed',latestRequest:'展示物理场'}};if(path.includes('/frontend'))return structuredClone(page);if(path.endsWith('/presenter'))lastState=body;return{};};
 const p=mountPresenter(ctx,call,async()=> 'task');
 try{p.request('task');await until(()=>finished);assert.equal(lastState.state,'waiting');page.browser.model={visible:true,ready:true,kind:'fields'};p.notify({status:'idle',session:{header:{origin:'interactive'}}});await until(()=>lastState.state==='idle');assert.equal(starts,1);}
 finally{for(const dispose of disposers)await dispose();}
});

test('an existing field receipt cannot end unfinished chart work; a fresh child continues with feedback',async t=>{
 const calls=new Map(),hooks=new Map(),disposers=[],prompts=[],states=[];
 let now=100000,runs=0;
 t.mock.method(Date,'now',()=>now);
 const page={revision:'field',presentationVersion:1,uiRevision:1,task:{request:'补齐结果'},browser:{connected:true,ready:true,presentationVersion:1,revision:1,errors:[]}};
 const task={status:'completed',request:'比较三组温度曲线',latestRequest:'补齐结果'};
 const ctx={tools:{},agentDefaultModel:{currentSelection:()=>({provider:'local',model:'test'})},agents:{create:async()=>({agent:{id:'owner'},dispose:async()=>{}})},on:(name,fn)=>hooks.set(name,fn),effect:fn=>disposers.push(fn()),subagents:{start:async(_provider,request)=>{
  const child={ctx:{tools:{register:d=>calls.set(d.name,d)}},session:{header:{parentSession:'owner'}}};hooks.get('agent/created')({agent:child});
  const invoke=(name,args)=>calls.get(name).execute(args,{agent:child,signal:request.signal});
  prompts.push(JSON.parse(request.prompt[0].text.split('\n').slice(1).join('\n')));
  await invoke('ui_read_skill',{});await invoke('ui_inspect',{target:'page'});
  const attempt=prompts.length;
  if(attempt===1)await invoke('ui_wait_for_render',{timeoutMs:0}); // Only the previous field is visible.
  if(attempt===2)await assert.rejects(invoke('ui_apply',{}),/完整 JSON/);
  if(attempt===3)await invoke('ui_apply',{expectedRevision:'field',operations:[{op:'replace',slot:'aside',value:{type:'table',id:'summary'}}]});
  const status=['pending','blocked','applied'][attempt-1];
  return{id:'child-'+attempt,result:Promise.resolve({stopReason:'completed',structured:{status,summary:attempt<3?'还缺对照表':'对照表已显示'}}),dispose:async()=>{runs++;}};
 }}};
 const call=async(path,body)=>{
  if(path.endsWith('/observe'))return{...facts('stable','completed'),dataRevision:'stable',task};
  if(path.endsWith('/presenter')){states.push(body);return{};}
  if(path.includes('/frontend')){
   if(body){page.revision='table';page.uiRevision=2;page.presentationVersion=2;page.browser.presentationVersion=2;page.browser.revision=2;}
   return structuredClone(page);
  }
  return{};
 };
 const h=mountPresenter(ctx,call,async()=> 'task'),agent={status:'idle',session:{header:{origin:'interactive'}}};
 try{
  h.request('task');await until(()=>runs===1);assert.equal(states.at(-1).state,'queued');assert.equal(states.at(-1).operator.confirmed,false);
  now+=13000;h.notify(agent);await until(()=>runs===2);assert.equal(states.at(-1).state,'queued');assert.match(prompts[1].validationFeedback,/对照表/);
  now+=13000;h.notify(agent);await until(()=>runs===3);assert.equal(prompts[2].calculationRequest,task.request);assert.match(prompts[2].validationFeedback,/完整 JSON/);
  assert.equal(states.at(-1).state,'idle');assert.equal(states.at(-1).operator.mutations,1);assert.equal(states.at(-1).operator.confirmed,true);
 }finally{for(const dispose of disposers)await dispose();}
});

test('a late browser receipt for an older result cannot swallow a CSV that appeared during the child',async t=>{
 const hooks=new Map(),disposers=[],tools=new Map(),states=[];
 let starts=0,disposals=0,now=100000,data='mesh';
 t.mock.method(Date,'now',()=>now);
 const page={revision:'view',task:{request:'展示现有结果'},presentationVersion:1,uiRevision:1,browser:{connected:false,ready:true,presentationVersion:1,revision:1,errors:[]}};
 const ctx={tools:{},agentDefaultModel:{currentSelection:()=>({provider:'local',model:'test'})},agents:{create:async()=>({agent:{id:'owner'},dispose:async()=>{}})},on:(name,fn)=>hooks.set(name,fn),effect:fn=>disposers.push(fn()),subagents:{start:async(_kind,request)=>{
  starts++;const child={ctx:{tools:{register:d=>tools.set(d.name,d)}},session:{header:{parentSession:'owner'}}};
  hooks.get('agent/created')({agent:child});const invoke=(name,args)=>tools.get(name).execute(args,{agent:child,signal:request.signal});
  await invoke('ui_read_skill',{});await invoke('ui_inspect',{target:'page'});
  await invoke('ui_apply',{expectedRevision:'view',update:{panelTitle:'已有结果'}});
  await invoke('ui_wait_for_render',{timeoutMs:0});data='new-csv';
  return{id:'worker',result:Promise.resolve({stopReason:'completed',structured:{status:starts===1?'pending':'applied',summary:'汇总'}}),dispose:async()=>{disposals++;}};
 }}};
 const call=async(path,body)=>{
  if(path.endsWith('/observe'))return{...facts(data,'completed'),task:{status:'completed',request:'展示现有结果'},dataRevision:data};
  if(path.endsWith('/presenter')){states.push(body);return{};}return structuredClone(page);
 };
 const p=mountPresenter(ctx,call,async()=> 'task');
 try{
  p.request('task');await until(()=>disposals===1);assert.equal(states.at(-1).state,'waiting');
  page.browser.connected=true;now+=13000;p.notify({status:'idle',session:{header:{origin:'interactive'}}});await until(()=>disposals===2);
  assert.equal(starts,2);assert.equal(states.filter(s=>s.state==='idle').length,1);assert.equal(states.at(-1).dataRevision,'new-csv');
 }finally{for(const dispose of disposers)await dispose();}
});
