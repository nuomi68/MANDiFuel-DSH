import test from 'node:test';
import assert from 'node:assert/strict';
import {SimulationApp} from '../assets/simulation-app.js';

test('the model follows the completed calculator run even for a table-only contract',()=>{
 const app=new SimulationApp({});
 app.data={spec:{outputs:[{kind:'statistic'}]},runs:[
  {id:'baseline',status:'completed'},{id:'edited',status:'completed'},{id:'failed',status:'failed'}
 ]};
 app.selected='edited';
 assert.equal(app.fieldRun,'edited');
 app.selected='baseline';
 assert.equal(app.fieldRun,null);
 app.selected='failed';
 assert.equal(app.fieldRun,null);
});
