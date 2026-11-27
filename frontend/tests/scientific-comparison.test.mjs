import test from 'node:test';
import assert from 'node:assert/strict';
import {comparisonReview,missingComparison} from '../native-plugin/scientific-comparison.mjs';

const table={type:'table',source:{kind:'dataset',dataset:'results'}};
const facts={task:{status:'completed'},workspaceHistory:[{file:'history.json',comparableResponses:{'reporting_response.rise':6}}],
 availableTables:[{file:'results.csv',rows:6}],presentation:{ui:{mode:'replace',datasets:{results:{file:'results.csv'}},root:table}}};
test('confirmed tables and a single spatial field do not supply a cross-case result graphic',()=>{
 const review=comparisonReview(facts);
 assert.deepEqual(review.tables,['results.csv']);assert(missingComparison(review,null,'给均值，再列表'));
 const ui=structuredClone(facts.presentation.ui);
 ui.aside={type:'tabs',children:[{id:'profile',type:'lineChart',series:[{source:{kind:'profile',view:'A'}}]}]};
 assert.deepEqual(comparisonReview({...facts,presentation:{ui}}).charts,[]);
 ui.aside.children.push({id:'scan',type:'scatterChart',series:[{source:table.source}]});
 assert.deepEqual(comparisonReview({...facts,presentation:{ui}}).charts,['scan']);
});
test('sampling, optimisation and single-case display requests keep different presentation choices',()=>{
 for(const kind of ['optimization','uncertainty']){
  const study={task:{status:'completed'},study:{kind,counts:{completed:4}},studyVariables:{responses:[{id:'peak'}]}};
  const review=comparisonReview(study);assert.equal(review.kind,kind);assert.equal(review.nativeOverview,true);
  assert.equal(missingComparison(review),false);
 }
 assert.equal(comparisonReview({...facts,workspaceHistory:[]}),null);
 const csvOnly=comparisonReview({...facts,workspaceHistory:[],availableTables:[{file:'results.csv',rows:6,hasCaseComparison:true}]});
 assert.equal(missingComparison(csvOnly,null,'分析温升'),true);
 assert.equal(comparisonReview({...facts,task:{status:'running'}}),null);
 assert.equal(comparisonReview({...facts,task:{status:'completed',displayOnly:true}}),null);
 const review=comparisonReview(facts),format={kind:'requested-format',reason:'只展示表格'};
 assert.equal(missingComparison(review,format,'请只展示表格'),false);
 assert.equal(missingComparison(review,format,'给结果'),true);
 assert.equal(missingComparison(review,{kind:'incomparable-data',reason:'两批温度采用不同的测点，未给出坐标。'}),false);
});

test('an input design can coexist with a response plot but cannot satisfy the result review alone',()=>{
 const task={...facts,workspaceHistory:[{file:'history.json',samples:[{point:{m:0.05,cp:1200}}],comparableResponses:{'response.rise':6}}]};
 const ui=structuredClone(facts.presentation.ui);
 ui.root={id:'design',type:'scatterChart',series:[{source:table.source,x:'m',y:'cp'}]};
 const review=()=>comparisonReview({...task,presentation:{ui}});
 assert.deepEqual(review().charts,[]);assert(missingComparison(review()));
 ui.root.series[0].y='rise';assert.deepEqual(review().charts,['design']);
 ui.datasets.results={file:'history.json',columns:[{id:'x',path:'point.m'},{id:'y',path:'point.cp'}]};
 Object.assign(ui.root.series[0],{x:'x',y:'y'});assert.deepEqual(review().charts,[]);
 ui.datasets.results.columns[1].path='response.rise';assert.deepEqual(review().charts,['design']);
});

test('formal studies distinguish design variables, a single best candidate and evaluated responses',()=>{
 const source={kind:'study'},series={source,x:'parameter.mass',y:'parameter.cp'};
 const ui={mode:'replace',root:{id:'scan',type:'scatterChart',series:[series]}};
 const review=()=>comparisonReview({task:{status:'completed'},study:{counts:{completed:4}},studyVariables:{responses:[{id:'rise'}]},presentation:{ui}});
 assert.deepEqual(review().charts,[]);
 series.y='response.rise';assert.deepEqual(review().charts,['scan']);
 source.select='best';assert.deepEqual(review().charts,[]);
});
