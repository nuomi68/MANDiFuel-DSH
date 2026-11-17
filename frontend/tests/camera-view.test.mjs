import test from 'node:test';
import assert from 'node:assert/strict';
import {ModelViewer} from '../assets/model-viewer.js';
function camera(){const v=Object.create(ModelViewer.prototype);v.camera={yaw:0,tilt:0,zoom:1,panX:0,panY:0};v.draw=()=>{};v.onCameraChange=()=>{};return v;}
test('requesting a preset can force a real camera reset even when already in that view mode',()=>{
 const v=camera();v.setView('3d');v.camera.yaw=2.4;v.camera.tilt=-.8;v.camera.panX=.5;v.setView('3d',true);
 assert.equal(v.camera.yaw,1.1);assert.equal(v.camera.tilt,.34);assert.equal(v.camera.panX,0);
});
test('XY is an actual orthographic orientation and reset also restores zoom',()=>{
 const v=camera();v.setView('xy');assert.equal(v.camera.yaw,0);assert.equal(v.camera.tilt,-Math.PI/2);
 v.camera.zoom=5;v.camera.panY=1;v.reset();assert.equal(v.camera.zoom,1);assert.equal(v.camera.panY,0);assert.equal(v.viewMode,'xy');
});
