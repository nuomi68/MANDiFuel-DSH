import test from 'node:test';
import assert from 'node:assert/strict';
import {extrema,markerText} from '../assets/extrema.js';
const points=[[1,0,0],[2,0,1],[3,0,2],[4,0,3]];
test('signed extrema preserve real cell centres and count ties',()=>{
 const markers=extrema([-7,4,4,-2],points);
 assert.deepEqual(markers.map(m=>[m.kind,m.value,m.index,m.count]),[['max',4,1,2],['min',-7,0,1]]);
 assert.deepEqual(markers[0].point,[2,0,1]);assert.match(markerText(markers[0],'Pa'),/并列 2 单元/);
});
test('a constant field has one honest combined label',()=>{
 const markers=extrema([1298,1298,1298,1298],points);
 assert.equal(markers.length,1);assert.equal(markers[0].kind,'constant');assert.match(markerText(markers[0],'K'),/最大＝最小 1298 K/);
});
test('changing a time frame moves the extrema to the correct original cells',()=>{
 assert.equal(extrema([1,9,4,2],points)[0].index,1);
 assert.equal(extrema([7,1,2,9],points)[0].index,3);
});
test('missing or misaligned centres never fabricate a position',()=>{
 assert.deepEqual(extrema([1,2],null),[]);assert.deepEqual(extrema([1,2],points),[]);
});
