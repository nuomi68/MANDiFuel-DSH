import test from 'node:test';
import assert from 'node:assert/strict';
import {presentationActivity,PresentationActivity} from '../assets/presentation-activity.js';

test('a final display error stays visible until the next attempt or task switch',()=>{
 const issue={}, host={dataset:{},setAttribute(){}},activity=new PresentationActivity(host,issue);
 activity.update({status:'completed',presenter:{state:'error',message:'曲线尚未提交'}});
 assert.equal(issue.hidden,false);assert.match(issue.textContent,/曲线尚未提交/);assert.equal(host.hidden,true);
 activity.update({status:'completed',presenter:{state:'queued',displayRequestRevision:1}});
 assert.equal(issue.hidden,true);assert.equal(issue.textContent,'');assert.equal(host.hidden,false);
 activity.update(null);assert.equal(issue.hidden,true);
});

test('computation keeps placeholders throughout UI worker idle, retry and acknowledgement gaps',()=>{
 for(const status of ['queued','starting','running','importing'])for(const state of ['idle','running','queued','waiting','warning','error']){
  assert.equal(presentationActivity({status,presenter:{state}}).active,true,`${status}/${state}`);
 }
});
test('terminal calculations hide placeholders during automatic publication, retries and browser confirmation',()=>{
 for(const status of ['completed','failed','stopped','interrupted']){
  for(const state of ['queued','running','waiting','idle','error','warning'])assert.equal(presentationActivity({status,presenter:{state}}).active,false);
 }
 assert.equal(presentationActivity({status:'completed'}).active,false);
});
test('a post-computation display request has its own waiting cycle',()=>{
 for(const state of ['queued','running','waiting','idle','warning','error']){
  const active=presentationActivity({status:'completed',presenter:{state,displayRequestRevision:2}}).active;
  assert.equal(active,['queued','running','waiting'].includes(state));
 }
});
test('task switches and empty drafts have no retained animation, and no status text is introduced',()=>{
 const host={dataset:{},setAttribute(k,v){this[k]=v;}},activity=new PresentationActivity(host);
 for(const task of [{status:'running',presenter:{state:'idle'}},{status:'completed',presenter:{state:'waiting'}},{status:'completed',presenter:{state:'idle'}}]){
  activity.update(task);assert.equal(host.hidden,!presentationActivity(task).active);assert.equal(host['aria-busy'],String(!host.hidden));
 }
 activity.update({draft:true,status:'queued'});assert.equal(host.hidden,true);
 activity.update(null);assert.equal(host.hidden,true);assert.equal(presentationActivity(null).label,'');
});
