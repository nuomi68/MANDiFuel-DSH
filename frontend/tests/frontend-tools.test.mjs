import test from 'node:test';
import assert from 'node:assert/strict';
import {attachFrontendTools,renderConfirmation,verifyRenderedSelection} from '../native-plugin/frontend-tools.mjs';

function setup(){
 const tools=new Map(),session={request:'调整显示'},signal=new AbortController().signal;
 const agent={ctx:{tools:{register:definition=>tools.set(definition.name,definition)}}};let commits=0;
 const page={revision:'r1',task:{request:'调整显示'},presentationVersion:2,uiRevision:1,viewStateRevision:0,browser:{connected:true,ready:true,presentationVersion:2,revision:1,errors:[]}};
 attachFrontendTools(agent,{id:'bound-task',session,current:()=>!session.closed,call:async(path,body)=>{assert(path.startsWith('/api/tasks/bound-task/frontend'));if(body){commits++;assert.equal(body.expectedRequest,'调整显示');return{revision:'r2',presentationVersion:2,uiRevision:1,viewStateRevision:0};}return structuredClone(page);}});
 return{session,page,agent,tools,commits:()=>commits,call:(name,args={},caller=agent)=>tools.get(name).execute(args,{agent:caller,signal})};
}
test('only calls from the bound UI operator announce tool activity',async()=>{
 const h=setup(),steps=[];h.session.reportActivity=async label=>steps.push(label);
 await assert.rejects(h.call('ui_inspect',{target:'data'},{}));
 await h.call('ui_read_skill');await h.call('ui_inspect',{target:'page'});await h.call('ui_inspect',{target:'data'});
 assert.deepEqual(steps,['读取展示规范','检查页面布局','检查结果数据']);
});
test('private tools require skill and actual observation, and reject foreign callers and unknown resources',async()=>{
 const h=setup();await assert.rejects(h.call('ui_apply',{expectedRevision:'r1',update:{}}),/SKILL/);
 await assert.rejects(h.call('ui_read_skill',{resource:'../../secrets'}),/未注册/);
 await h.call('ui_read_skill');await assert.rejects(h.call('ui_apply',{expectedRevision:'r1',update:{}}),/ui_inspect/);
 await assert.rejects(h.call('ui_inspect',{target:'page'},{}),/失效/);
 await h.call('ui_inspect',{target:'page'});await h.call('ui_apply',{expectedRevision:'r1',operations:[{op:'update',slot:'main',id:'note',props:{text:'新说明'}}]});assert.equal(h.commits(),1);
 const rendered=await h.call('ui_wait_for_render',{timeoutMs:0});assert.equal(rendered.status,'confirmed');assert.equal(h.session.confirmed,true);
});
test('configuration saved while the browser is offline remains unconfirmed',async()=>{
 const h=setup();await h.call('ui_read_skill');await h.call('ui_inspect',{target:'page'});await h.call('ui_apply',{expectedRevision:'r1',update:{rendering:{palette:'viridis'}}});h.page.browser.connected=false;
 assert.equal((await h.call('ui_wait_for_render',{timeoutMs:0})).status,'offline');assert.equal(h.session.confirmed,false);
});
test('malformed writes give actionable feedback and only accepted transactions count',async()=>{
 const h=setup();await h.call('ui_read_skill');await h.call('ui_inspect',{target:'page'});
 await assert.rejects(h.call('ui_apply',{}),/完整 JSON/);
 assert.match(h.session.applyError,/括号/);assert.equal(h.commits(),0);
 const first=await h.call('ui_apply',{expectedRevision:'r1',datasets:{summary:{file:'results.csv'}}});
 await h.call('ui_apply',{expectedRevision:first.revision,update:{panelTitle:'汇总'}});
 assert.equal(h.session.mutations,2);assert.equal(h.session.applyError,null);
});
test('a newer user instruction cannot be adopted by the older operator session',async()=>{
 const h=setup();let cancelled=false;h.session.cancel=()=>{cancelled=true;h.session.closed=true;};h.page.task.request='新要求';
 await assert.rejects(h.call('ui_inspect',{target:'page'}),/新的用户请求/);assert.equal(cancelled,true);await assert.rejects(h.call('ui_apply',{expectedRevision:'r1',update:{}}),/失效/);
});
test('an old UI acknowledgement cannot confirm a newer style or interaction update',()=>{
 const wanted={presentationVersion:3,uiRevision:1,interactionRevision:2};
 const page={browser:{connected:true,ready:true,presentationVersion:2,revision:1,interactionRevision:1,errors:[]}};
 assert.equal(renderConfirmation(page,wanted),'pending');page.browser.presentationVersion=3;assert.equal(renderConfirmation(page,wanted),'pending');page.browser.interactionRevision=2;assert.equal(renderConfirmation(page,wanted),'confirmed');
 page.browser.connected=false;assert.equal(renderConfirmation(page,wanted),'offline');
});

test('a settings snapshot alone cannot authorize editing an unseen page',async()=>{
 const h=setup();await h.call('ui_read_skill');await h.call('ui_inspect',{target:'settings'});await assert.rejects(h.call('ui_apply',{expectedRevision:'r1',update:{}}),/当前实际页面/);
});
test('completion requires the actual physical field window when fields are available',()=>{
 const page={modelRequirement:{required:true,kind:'fields'},browser:{connected:true,ready:true,presentationVersion:1,revision:1,errors:[],model:{visible:true,ready:true,kind:'mesh'}}};
 const wanted={presentationVersion:1,uiRevision:1};assert.equal(renderConfirmation(page,wanted),'pending');page.browser.model.kind='fields';assert.equal(renderConfirmation(page,wanted),'confirmed');page.browser.model.visible=false;assert.equal(renderConfirmation(page,wanted),'error');
});

test('a generated layout gets one real selection check, also when the presenter confirms on its behalf',async()=>{
 const session={checkSelection:true},page={revision:'seen',browser:{model:{kind:'fields'},browserId:'live'}};let count=0;
 const call=async(path,body)=>{assert.equal(path,'/api/tasks/task/selection-check');assert.deepEqual(body,{revision:'seen'});count++;return{status:'verified',restored:true};};
 await verifyRenderedSelection(session,page,call,'task');await verifyRenderedSelection(session,page,call,'task');
 assert.equal(count,1);assert.equal(session.selectionCheck.status,'verified');
 await verifyRenderedSelection({checkSelection:true},{browser:{model:{kind:'mesh'},browserId:'live'}},call,'task');assert.equal(count,1);
});

test('receipt versions take precedence over old render errors and late browser reports',()=>{
 const wanted={uiRevision:3,presentationVersion:5},page={browser:{connected:true,ready:true,revision:2,presentationVersion:4,errors:[{id:'old'}]}};
 assert.equal(renderConfirmation(page,wanted),'pending');
 page.presentationVersion=6;assert.equal(renderConfirmation(page,wanted),'stale');
 page.presentationVersion=5;Object.assign(page.browser,{revision:3,presentationVersion:5});assert.equal(renderConfirmation(page,wanted),'error');
});

test('a table-only page can confirm without a viewer while retaining real component errors',()=>{
 const page={modelRequirement:{required:false},viewer:{rendererError:'obsolete',revision:1},browser:{connected:true,ready:true,presentationVersion:4,errors:[]}};
 const expected={presentationVersion:4,viewStateRevision:2};
 assert.equal(renderConfirmation(page,expected),'confirmed');
 delete page.browser.ready;assert.equal(renderConfirmation(page,expected),'pending');
 page.browser.errors.push({id:'table'});assert.equal(renderConfirmation(page,expected),'error');
});

test('only selection-bearing edits trigger automatic switching and an explicit check needs proof',async()=>{
 const h=setup();await h.call('ui_read_skill');await h.call('ui_inspect',{target:'page'});
 const tabs={id:'notes',type:'tabs',children:[{id:'a',type:'text',text:'甲'},{id:'b',type:'text',text:'乙'}]};
 await h.call('ui_apply',{expectedRevision:'r1',operations:[{slot:'main',op:'insert',value:tabs}]});
 assert.equal(!!h.session.checkSelection,false);
 await h.call('ui_apply',{expectedRevision:'r2',operations:[{slot:'main',op:'update',props:{source:{kind:'dataset',selection:{viewColumn:'view'}}}}]});
 assert.equal(h.session.checkSelection,true);
 h.session.selectionCheck={status:'not-applicable'};
 assert.equal((await h.call('ui_wait_for_render',{timeoutMs:0})).status,'confirmed');
 assert.equal((await h.call('ui_wait_for_render',{verifySelection:true,timeoutMs:0})).status,'selection-unconfirmed');
 assert.equal(h.session.confirmed,false);
});
