import test from 'node:test';import assert from 'node:assert/strict';
import {feasible,observations,statistics,histogram,bestHistory,pareto,nearestFrame} from '../assets/study-math.js';
const study={responses:[{id:'T',goal:'min',bounds:{max:100}},{id:'life',goal:'max'}],runs:[]};
const run=(id,T,life=1,status='completed')=>({id,status,parameters:{},responses:{T,life}});
test('failed and missing evaluations are not numeric samples',()=>{const s={...study,runs:[run('a',5),run('bad',-999,1,'failed'),run('missing',undefined)]};assert.deepEqual(observations(s,'T').map(r=>r.value),[5]);});
test('best-so-far uses feasible completed responses and objective direction',()=>{const s={...study,runs:[run('infeasible',110),run('a',90),run('bad',-100,1,'failed'),run('b',80),run('missing',undefined)]};assert.deepEqual(bestHistory(s,'T').map(p=>p.best?.value??null),[null,90,90,80,80]);assert.equal(feasible(s,s.runs[4]),null);});
test('maximization is independent of input arrival ordering',()=>{const s={responses:[{id:'life',goal:'max'}],runs:[{...run('a',5,2),iteration:3},{...run('b',5,8),iteration:1}]};assert.deepEqual(bestHistory(s,'life').map(p=>p.best.value),[8,8]);});
test('empirical quantiles and sample standard deviation have explicit meaning',()=>{const s=statistics([1,2,3,4,5].map(value=>({value})));assert.equal(s.mean,3);assert.equal(s.p5,1.2);assert.equal(s.p95,4.8);assert.equal(s.sd,Math.sqrt(2.5));assert.equal(statistics([{value:7}]).sd,null);});
test('histogram includes maximum boundary and constant samples once',()=>{const rows=[0,1,2,3,4].map((value,i)=>({value,run:{id:String(i)}})),bins=histogram(rows,4);assert.equal(bins.reduce((a,b)=>a+b.runs.length,0),5);assert.equal(bins.at(-1).runs.length,2);assert.equal(histogram([{value:4,run:{id:'a'}},{value:4,run:{id:'b'}}]).length,1);});
test('mixed-direction Pareto candidates exclude dominated and failed observations',()=>{const s={...study,runs:[run('a',10,2),run('b',20,5),run('dominated',30,1),run('failed',1,8,'failed'),run('invalid',110,100)]};assert.deepEqual([...pareto(s,'T','life')],['a','b']);});

test('parameter switching chooses the same physical time, rather than the old frame index',()=>{assert.equal(nearestFrame([{time:0},{time:5},{time:10},{time:15}],10),2);assert.equal(nearestFrame([{time:0},{time:8},{time:12}],10),1);});
