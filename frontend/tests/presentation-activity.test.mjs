import test from 'node:test';
import assert from 'node:assert/strict';
import {presentationActivity,PresentationActivity} from '../assets/presentation-activity.js';

test('computation keeps placeholders throughout UI worker idle, retry and acknowledgement gaps',()=>{
 for(const status of ['queued','starting','running','importing'])for(const state of ['idle','running','queued','waiting','warning','error']){
  assert.equal(presentationActivity({status,presenter:{state}}).active,true,`${status}/${state}`);
 }
});
test('completed calculation waits for the final frontend work and clears on acknowledgement or final failure',()=>{
 for(const status of ['completed','failed','stopped','interrupted']){
  for(const state of ['queued','running','waiting'])assert.equal(presentationActivity({status,presenter:{state}}).active,true);
  for(const state of ['idle','error','warning'])assert.equal(presentationActivity({status,presenter:{state}}).active,false);
 }
 assert.equal(presentationActivity({status:'completed'}).active,false);
});
test('task switches and empty drafts have no retained animation, and no status text is introduced',()=>{
 const host={dataset:{},setAttribute(k,v){this[k]=v;}},activity=new PresentationActivity(host);
 for(const task of [{status:'running',presenter:{state:'idle'}},{status:'completed',presenter:{state:'waiting'}},{status:'completed',presenter:{state:'idle'}}]){
  activity.update(task);assert.equal(host.hidden,!presentationActivity(task).active);assert.equal(host['aria-busy'],String(!host.hidden));
 }
 activity.update({draft:true,status:'queued'});assert.equal(host.hidden,true);
 activity.update(null);assert.equal(host.hidden,true);assert.equal(presentationActivity(null).label,'');
});
