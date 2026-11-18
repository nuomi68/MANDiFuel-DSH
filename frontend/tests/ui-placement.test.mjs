import test from 'node:test';
import assert from 'node:assert/strict';
import {hasWorkspaceContent,settingsControlGroups,groupSettingsControls,uiInScope,caseTabs} from '../assets/ui-placement.js';
import {fieldSummary} from '../assets/field-summary.js';

test('single-case pages remain visible for model/overview scopes while studies retain separate tabs',()=>{
 for(const scope of ['all','model','overview'])assert.equal(uiInScope({scope},{hasStudy:false,state:{panel:'overview'}}),true);
 assert.equal(uiInScope({scope:'model'},{hasStudy:true,state:{panel:'overview'}}),false);assert.equal(uiInScope({scope:'model'},{hasStudy:true,state:{panel:'model'}}),true);assert.equal(uiInScope(null,{hasStudy:false}),false);
});

test('generated operation groups default to settings regardless of their titles or identifiers',()=>{
 const document={root:{id:'layout',type:'grid',children:[{id:'newFeature',type:'controls',title:'任意操作组',ids:['a','b']},{id:'nested',type:'tabs',children:[{id:'other',type:'controls',ids:['a','c']}]}]}};
 assert.equal(hasWorkspaceContent(document.root),false);
 const groups=settingsControlGroups(document);
 assert.equal(groups.length,2);
 assert.deepEqual(groupSettingsControls(['a','b','c','d'].map(id=>({id})),groups,document).map(c=>c.id),['d','a','b','c']);
});

test('inline controls are explicit and hidden settings groups respect ancestor visibility',()=>{
 const document={root:{id:'layout',type:'column',children:[{id:'hidden',type:'column',children:[{id:'ops',type:'controls',ids:['a']}]},{id:'besideChart',type:'controls',placement:'inline',ids:['b']},{id:'chart',type:'lineChart'}]}};
 const groups=settingsControlGroups(document,n=>n.id!=='hidden');
 assert.equal(hasWorkspaceContent(document.root),true);
 assert.deepEqual(groups,[]);
 assert.deepEqual(groupSettingsControls(['a','b','c'].map(id=>({id})),groups,document),[{id:'c'}]);
});

test('uniformity is a property of actual frame values and never of the expanded display range',()=>{
 assert.deepEqual(fieldSummary([650,650,650]),{min:650,max:650,uniform:true});
 assert.equal(fieldSummary([650,650.000001]).uniform,false);
 assert.equal(fieldSummary([]).uniform,false);
});

test('only distinct single-view panels steer the model from a case tab',()=>{
 const chart=(id,views)=>({id,series:views.map(view=>({source:{view}}))});
 const table={id:'table',source:{kind:'dataset',selection:{view:'b'}}};
 assert.deepEqual([...caseTabs([chart('first',['a','a']),{id:'second',children:[table]}])],[['first','a'],['second','b']]);
 assert.deepEqual([...caseTabs([chart('first',['a']),table,chart('comparison',['a','b']),{id:'notes',type:'text'}])],[['first','a'],['table','b']]);
 for(const panels of [[chart('a',['a','b']),table],[chart('a',['b']),table],[chart('a',['a']),{id:'table',source:{kind:'dataset'}}]])assert.equal(caseTabs(panels),null);
});
