import test from 'node:test';
import assert from 'node:assert/strict';
import {paletteBytes,gradient} from '../assets/render-style.js';
test('custom color instructions have exact endpoints and a consistent legend',()=>{
 const p=[[0,'#0000ff'],[.5,'#00ff00'],[1,'#ff0000']],bytes=paletteBytes(p);
 assert.deepEqual([...bytes.slice(0,4)],[0,0,255,255]);assert.deepEqual([...bytes.slice(-4)],[255,0,0,255]);assert.match(gradient(p),/#00ff00 50%/);
 const reversed=paletteBytes(p,true);assert.deepEqual([...reversed.slice(0,4)],[255,0,0,255]);assert.match(gradient(p,true),/#ff0000 0%/);
});
