import test from 'node:test';import assert from 'node:assert/strict';
import {chartSVG,heatmapSVG,tableColumns,tableRows,formatCell,chartDataTable,tableCSV} from '../assets/chart-view.js';
import {resolveSource,studyTable} from '../assets/data-sources.js';
import {zoomViewport,centeredZoom} from '../assets/chart-navigation.js';
const table={columns:[{id:'x',label:'时间',unit:'s'},{id:'value',label:'温度',unit:'K'}],rows:[{x:0,value:300},{x:1,value:320},{x:2,value:310}]};
test('mixed marks preserve requested marker, line style, step and target bands in exported SVG',()=>{
 const svg=chartSVG({id:'mixed',type:'chart',references:[{axis:'y',from:305,to:315,label:'容差',color:'#008800'},{axis:'x',value:1,label:'阶段分界'}]},[{label:'实际点',mark:'scatter',marker:'square',color:'#ff8800',table},{label:'最好值',mark:'line',step:true,dash:'dash',color:'#008800',table}]);
 assert.match(svg,/stroke-dasharray="7 4"/);assert.match(svg,/实际点/);assert.match(svg,/最好值/);assert.match(svg,/容差/);assert.match(svg,/阶段分界/);assert.match(svg,/fill="#ff8800"/);assert.match(svg,/H[\d.]+V[\d.]+/);assert(!/NaN|Infinity/.test(svg));
});
test('log axes require positive actual points and references instead of dropping invalid data',()=>{
 const positive={...table,rows:[{x:1,value:.3},{x:2,value:.005},{x:3,value:.0005}]};
 assert.match(chartSVG({type:'lineChart',yAxis:{scale:'log'},references:[{axis:'y',value:.005,label:'停止容差'}]},[{label:'偏差',table:positive}]),/停止容差/);
 assert.throws(()=>chartSVG({type:'lineChart',yAxis:{scale:'log'}},[{label:'偏差',table:{...positive,rows:[{x:1,value:0}]}}]),/正数/);
 assert.throws(()=>chartSVG({type:'lineChart',yAxis:{scale:'log'},references:[{axis:'y',value:0}]},[{label:'偏差',table:positive}]),/正数/);
});
test('interval marks use genuine bound columns and reject reversed bounds',()=>{
 const t={columns:[{id:'lo'},{id:'hi'},{id:'iteration'}],rows:[{lo:1,hi:15.5,iteration:1},{lo:3.7,hi:3.83,iteration:8}]};
 const svg=chartSVG({type:'intervalChart',yAxis:{reverse:true}},[{label:'保留区间',xLow:'lo',xHigh:'hi',y:'iteration',marker:'none',table:t}]);assert.match(svg,/保留区间/);assert.match(svg,/1, 15.5/);assert.throws(()=>chartSVG({type:'intervalChart'},[{label:'区间',xLow:'lo',xHigh:'hi',y:'iteration',table:{...t,rows:[{lo:5,hi:2,iteration:1}]}}]),/下限/); // legend/title include actual endpoints via point titles below
});
test('heatmaps keep zero and missing values distinct and never silently average repeated coordinates',()=>{
 const t={columns:[{id:'a'},{id:'b'},{id:'value',unit:'K'}],rows:[{a:1,b:1,value:0},{a:2,b:1,value:2},{a:1,b:2,value:3}]},node={type:'heatmapChart',x:'a',y:'b',value:'value',valueDigits:1};
 const svg=heatmapSVG(node,t);assert.equal((svg.match(/data-value="missing"/g)||[]).length,1);assert.match(svg,/data-value="0"/);assert.match(svg,/>0\.0<\/text>/);
 assert.throws(()=>heatmapSVG(node,{...t,rows:[...t.rows,t.rows[0]]}),/重复/);
 const constant=heatmapSVG(node,{...t,rows:[{a:1,b:1,value:0}]});assert.match(constant,/有效网格均为 0/);
});
test('series with different physical units must use separate axes or panels',()=>{
 assert.throws(()=>chartSVG({type:'chart'},[{label:'T',table},{label:'p',table:{...table,columns:[{id:'x',unit:'s'},{id:'value',unit:'Pa'}]}}]),/不同单位/);
});
test('tables expose explicit formats, stable sorting, search and last-place missing values without changing raw data',()=>{
 const t={columns:[{id:'name'},{id:'value',unit:'m'}],rows:[{name:'b',value:null},{name:'a',value:0},{name:'c',value:2}]};
 const cols=tableColumns(t,{columns:[{id:'value',format:'scientific',digits:2}]});assert.equal(formatCell(2e-6,cols[0]),'2.00e-6');assert.equal(formatCell(null,cols[0]),'—');assert.equal(formatCell(0,{format:'fixed',digits:2}),'0.00');
 assert.deepEqual(tableRows(t,{sort:{column:'value',direction:'desc'}}).map(r=>r.name),['c','a','b']);assert.equal(tableRows(t,{query:'a'})[0].value,0);assert.equal(t.rows[0].value,null);
});
test('study tables and phase-filtered best-so-far series work without a model or fabricated missing responses',async()=>{
 const s={parameters:[{id:'phase',type:'category'}],responses:[{id:'T',label:'温度',unit:'K',goal:'min'}],runs:[{id:'a',status:'completed',parameters:{phase:'初始'},responses:{T:320}},{id:'b',status:'failed',parameters:{phase:'搜索'},responses:{}},{id:'c',status:'completed',parameters:{phase:'搜索'},responses:{T:310}}]};
 const raw=studyTable(s,{status:'all',best:'T'});assert.equal(raw.rows[1]['response.T'],undefined);assert.equal(raw.rows[1]['best.T'],320);assert.equal(raw.rows[2]['best.T'],310);assert.equal(raw.rows[0].iteration,undefined);
 const result=await resolveSource({kind:'study',best:'T',filter:[{column:'parameter.phase',op:'eq',value:'搜索'}]},{getStudyData:async()=>s});assert.equal(result.rows.length,1);assert.equal(result.rows[0].runId,'c');
});
test('best-case metrics use all fields from the same feasible run and status codes remain filterable',async()=>{
 const s={parameters:[{id:'E'}],responses:[{id:'error',goal:'min'},{id:'T',bounds:{max:350}}],runs:[{id:'a',status:'completed',parameters:{E:50},responses:{error:3,T:320}},{id:'b',status:'completed',parameters:{E:80},responses:{error:.1,T:400}},{id:'c',status:'completed',parameters:{E:75},responses:{error:.5,T:330}},{id:'d',status:'failed',parameters:{E:70},responses:{}}]};
 const t=studyTable(s,{best:'error',select:'best'});assert.equal(t.rows.length,1);assert.equal(t.rows[0].runId,'c');assert.equal(t.rows[0]['parameter.E'],75);assert.equal(t.rows[0]['response.T'],330);assert.equal(t.rows[0]['best.error'],.5);assert(!t.columns.some(c=>c.id==='best.E'));
 const completed=await resolveSource({kind:'study',status:'all',filter:[{column:'statusCode',op:'eq',value:'completed'}]},{getStudyData:async()=>s});assert.equal(completed.rows.length,3);assert.equal(completed.rows[0].status,'已完成');
 assert.equal(studyTable({...s,runs:[s.runs[1]]},{best:'error',select:'best'}).rows.length,0);
});
test('mixed chart CSV retains real interval endpoints, units, categories and missing values',()=>{
 const table={columns:[{id:'series'},{id:'lo',unit:'GPa'},{id:'hi',unit:'GPa'},{id:'iteration'}],rows:[{series:'二分',lo:75,hi:81.25,iteration:7},{series:'诊断',lo:null,hi:null,iteration:8}]};
 const exported=chartDataTable([{label:'保留区间',table}]);assert.equal(exported.columns[0].id,'_series');assert.equal(exported.columns.find(c=>c.id==='lo').unit,'GPa');assert.equal(exported.rows[0].hi,81.25);assert.equal(exported.rows[1].lo,null);assert.equal(table.rows[0]._series,undefined);assert.match(tableCSV(exported),/"二分","75","81.25","7"/);
});
test('interactive marks keep original record identity after sorting, support legend toggles and retain export data',()=>{
 const t={columns:[{id:'x'},{id:'value'},{id:'runId'}],rows:[{x:2,value:20,runId:'b'},{x:1,value:10,runId:'a'}]},s=[{label:'实际点',table:t,order:'x',marker:'circle'}];
 const svg=chartSVG({type:'chart'},s,{},650);assert.match(svg,/data-chart-point="0:0"[^>]*data-chart-run="b"/);assert.match(svg,/data-chart-point="0:1"[^>]*data-chart-run="a"/);assert.match(svg,/data-chart-legend="series:0"[^>]*aria-pressed="true"/);assert.match(svg,/data-chart-domain=/);
 const hidden=chartSVG({type:'chart'},s,{},650,{hidden:new Set(['series:0'])});assert(!hidden.includes('data-chart-point='));assert.match(hidden,/aria-pressed="false"/);assert.equal(t.rows.length,2);
});
test('navigation respects logarithmic and reversed axes and never transforms stored observations',()=>{
 const d={x:{min:10,max:1000,scale:'log'},y:{min:0,max:10,scale:'linear',reverse:true}},v=zoomViewport(d,{x:[.25,.75],y:[.2,.8]});assert(Math.abs(v.x[0]-Math.sqrt(1000))<1e-10);assert(Math.abs(v.x[1]-Math.sqrt(100000))<1e-10);assert(Math.abs(v.y[0]-2)<1e-12);assert(Math.abs(v.y[1]-8)<1e-12);
 assert(centeredZoom(d,1.25).x[0]<10);assert.equal(d.x.min,10);assert.throws(()=>zoomViewport(d,{x:[.5,.5],y:[.2,.8]}),/无效/);
});
test('explicit dataset identity mapping adds linked run IDs without mutating the original table',async()=>{
 const raw={columns:[{id:'case'},{id:'value'}],rows:[{case:'runA',value:0}]};const t=await resolveSource({kind:'dataset',dataset:'d',runId:'case'},{getDataset:async()=>raw});assert.equal(t.rows[0].runId,'runA');assert.equal(t.rows[0].value,0);assert(!raw.columns.some(c=>c.id==='runId'));assert.equal(raw.rows[0].runId,undefined);
});
