import assert from 'node:assert/strict';
import test from 'node:test';
import {caseParameterSections,readbackSections,receiptFor} from '../assets/model-parameters.js';
import {evidenceGroups,EvidenceBrowser} from '../assets/evidence-browser.js';

test('only the selected case supplies a registered input receipt and its parameter groups',()=>{
 const files=['a/prepare.json','a/other/prepare.json','prepare.json','b/prepare.json'].map(path=>({path,bytes:64}));
 assert.equal(receiptFor(files,'a'),files[0]);assert.equal(receiptFor(files,'.'),files[2]);
 assert.equal(receiptFor(files,undefined),null);assert.equal(receiptFor(files,'c'),undefined);
 assert.equal(receiptFor([{path:'a/prepare.json',bytes:1024*1024}],'a'),undefined);
 const shared={title:'固定几何'},local={caseRoot:'a'},other={caseRoot:'b'};
 assert.deepEqual(caseParameterSections([shared,local,other],'a'),[shared,local]);
 assert.deepEqual(caseParameterSections([shared,local,other],null),[shared]);
});
test('use flat or structured readbacks, never an edit request as the executed value',()=>{
 const entry='boundaryField/wall/massFlowRate',edits=[{entry,value:8},{entry:'absent',value:42}];
 const flat=readbackSections({edits,[entry]:'0.045','materials/rod/material':'constant'});
 assert.deepEqual(flat.map(s=>s.title),['本工况输入','材料区 · rod']);
 assert.deepEqual(flat[0].items.map(r=>[r.label,r.value,r.unit]),[['质量流量',0.045,'kg/s']]);
 const structured=readbackSections({edits,readback:[{file:'0/T',entry,value:'0.044'}],fixed_inputs:{other:'specified'},rodDict_readback:{rInnerFuel:'4.3'}});
 assert.equal(structured[0].items[0].value,0.044);assert.equal(structured[2].items[0].unit,'');
 assert.deepEqual(readbackSections({edits}),[]);
});
test('group identical endpoint receipts only and retain each case, status, unit and execution outcome',()=>{
 const base={key:'execution.final_time',value:10,unit:'s',timeUnit:'s',status:'verified',execution:'verified'};
 const end=(id,patch={})=>({...base,id,caseRoot:id,...patch});
 const claims=[end('a'),end('heat1',{key:'heat.source',status:'failed'}),end('b'),end('heat2',{key:'heat.source',status:'failed'}),
  end('different',{value:20}),end('days',{unit:'d'}),end('incomplete',{execution:'not_verified'}),end('stale',{status:'stale'})];
 const grouped=evidenceGroups(claims);
 assert.deepEqual(grouped.filter(g=>g.length>1).map(g=>g.map(c=>c.id)),[['a','b']]);
 assert.deepEqual(grouped.slice(0,2).map(g=>g[0].id),['heat1','heat2']);
 assert.equal(grouped.flat().length,claims.length);
});
test('index polls coalesce without cancelling a slow evidence detail or redrawing unchanged detail',async()=>{
 const browser=Object.create(EvidenceBrowser.prototype);
 Object.assign(browser,{task:{id:'task-a'},map:new Map(),dialog:{open:true},selected:'a',renderDetail:(id,data)=>painted.push([id,data])});
 const waits=[],painted=[];
 browser.api=(query,signal)=>new Promise(resolve=>waits.push({query,signal,resolve}));
 const index={revision:'r',claims:[{id:'a',caseRoot:'one'}],cases:[{caseRoot:'one',state:'ready',revision:'v'}]};
 browser.data=index;browser.map.set('a',index.claims[0]);
 const detail=browser.select('a'),poll=browser.refresh();await browser.refresh();assert.equal(waits.length,2);
 waits[1].resolve(index);await poll;assert.equal(waits.length,2);assert.equal(waits[0].signal.aborted,false);
 waits[0].resolve('detail');await detail;assert.deepEqual(painted,[['a','detail']]);
 const next=browser.refresh();waits[2].resolve(index);await next;assert.equal(waits.length,3);
 const old=browser.select('a');browser.cancelDetail();waits[3].resolve('old detail');await old;
 assert.deepEqual(painted,[['a','detail']]);
});
