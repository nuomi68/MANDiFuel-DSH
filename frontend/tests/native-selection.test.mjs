import test from 'node:test';import assert from 'node:assert/strict';
import {NativeHarness} from '../assets/native-harness.js';
test('native initial selection cannot replace the chosen task before handshake; deliberate later switches still work',()=>{
 const old={id:'old',nativeSessionId:'old-session'},current={id:'current',nativeSessionId:'current-session'},selected=[],listeners=new Map(),frame={contentWindow:{},dataset:{},addEventListener(){}};
 const globals=Object.fromEntries(['window','document','location','matchMedia','innerWidth'].map(k=>[k,globalThis[k]]));
 globalThis.window={addEventListener:(type,fn)=>listeners.set(type,fn)};globalThis.document={getElementById:id=>id==='native-dsh'?frame:{addEventListener(){}}};globalThis.location={origin:'http://localhost'};globalThis.matchMedia=()=>({matches:false,addEventListener(){}});globalThis.innerWidth=1300;
 try{
  const h=new NativeHarness({getTasks:()=>[old,current],selectTask:id=>selected.push(id)}),message=data=>listeners.get('message')({origin:location.origin,source:frame.contentWindow,data:{type:'mandifuel-native-selected',...data}});
  message({sessionId:'old-session'});assert.deepEqual(selected,[]);h.current=current;message({sessionId:'old-session'});assert.deepEqual(selected,[]);
  h.ready=true;h.pendingSession='current-session';message({sessionId:'old-session'});assert.deepEqual(selected,[]);message({sessionId:'current-session'});assert.equal(h.pendingSession,null);assert.deepEqual(selected,[]);
  message({sessionId:'old-session'});assert.deepEqual(selected,['old']);
 }finally{for(const[k,v]of Object.entries(globals))v===undefined?delete globalThis[k]:globalThis[k]=v;}
});
