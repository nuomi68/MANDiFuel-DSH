// Chat, input, model choices and execution controls belong to native Harness.
import {TaskSnapshots} from './task-snapshots.js';
export const statusLabel={draft:'等待输入',queued:'等待执行',starting:'连接 DSH',running:'执行中',importing:'整理结果',completed:'已完成',failed:'执行失败',stopped:'已停止',interrupted:'已中断'};
const BASE='/workbench',$=id=>document.getElementById(id);
export class NativeHarness{
 constructor(cb){this.cb=cb;this.current=null;this.token=null;this.events=null;this.selection=0;this.ready=false;this.pendingSession=null;this.open=innerWidth>900;this.moving=false;this.media=matchMedia('(max-width:900px)');this.frame=$('native-dsh');this.defaultEvents=null;this.defaultWatchId=null;this.selectedNativeSession=null;this.snapshots=new TaskSnapshots();this.polling=false;
  $('dsh-button').addEventListener('click',()=>this.toggle());$('new-task-button').addEventListener('click',()=>this.newTask().catch(error=>this.connectionError(error)));
  $('retry-native').addEventListener('click',()=>this.retry());
  $('dsh-window').addEventListener('close',()=>{if(!this.moving&&!$('dsh-window').open){this.open=false;this.sync();}});this.media.addEventListener('change',()=>this.sync());
  this.frame.addEventListener('load',()=>this.ping());this.frame.addEventListener('error',()=>this.connectionError(new Error('原生 DSH 页面未能加载，请重新连接。')));
  window.addEventListener('message',event=>{
   if(event.origin!==location.origin||event.source!==this.frame.contentWindow)return;
   if(event.data?.type==='mandifuel-native-ready'){this.ready=true;clearInterval(this.handshake);clearTimeout(this.connectTimeout);this.connectionState('ready');this.navigate();}
   if(event.data?.type==='mandifuel-native-error')this.connectionError(new Error(event.data.message));
   if(event.data?.type==='mandifuel-native-selected'){this.selectedNativeSession=event.data.sessionId;this.frame.dataset.activeSession=event.data.sessionId||'';if(this.pendingSession&&event.data.sessionId!==this.pendingSession)return;if(event.data.sessionId===this.pendingSession)this.pendingSession=null;if(!this.ready||!this.current)return;const task=event.data.sessionId?cb.getTasks().find(t=>t.nativeSessionId===event.data.sessionId||t.nativeSessionIds?.includes(event.data.sessionId)):null;if(task&&event.data.title)this.syncTitle(task,event.data.sessionId,event.data.title);if(task&&task.id!==this.current?.id&&!task.draft)cb.selectTask(task.id);}
  });window.addEventListener('pagehide',()=>{this.events?.close();this.defaultEvents?.close();clearInterval(this.handshake);clearTimeout(this.connectTimeout);clearInterval(this.reconcileTimer);this.reconcileTimer=null;});
  window.addEventListener('pageshow',event=>{if(event.persisted){if(this.defaultTask){this.defaultWatchId=null;this.watchDraft(this.defaultTask);}if(this.current)this.select(this.current).catch(error=>this.cb.onError?.(error.message));}});
  window.addEventListener('online',()=>this.reconcile());
  window.addEventListener('visibilitychange',()=>{if(!document.hidden)this.reconcile();});
 }
 receive(meta){if(!this.snapshots.accept(meta))return false;if(this.current?.id===meta.id)this.current=meta;if(this.defaultTask?.id===meta.id)this.defaultTask=meta;this.cb.onMeta(meta);return true;}
 async reconcile(){
  if(this.polling||document.hidden||!this.current)return;
  const selection=this.selection,id=this.current.id;this.polling=true;
  try{const r=await fetch(`${BASE}/api/tasks/${id}`,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});if(r.ok){const snapshot=await r.json();if(selection===this.selection&&this.current?.id===id)this.receive(snapshot.task);}}
  catch{/* Keep the last known state while SSE and recovery reads reconnect. */}
  finally{this.polling=false;}
 }
 connectionState(state,message){$('dsh-window').dataset.connection=state;$('native-connection').hidden=state==='ready';$('native-spinner').hidden=state==='error';$('native-connection-actions').hidden=state!=='error';$('native-connection-label').textContent=message||'正在连接原生 DSH…';}
 async syncTitle(task,sessionId,title){if(!this.token||typeof title!=='string'||!title.trim()||title.length>200||task.title===title)return;const key=JSON.stringify([task.id,title]);if(this.titleSync===key)return;this.titleSync=key;try{const r=await fetch(`${BASE}/api/tasks/${task.id}/native-event`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Workbench-Token':this.token},body:JSON.stringify({kind:'title',title,sessionId})});if(!r.ok)throw new Error('标题尚未同步');this.receive((await r.json()).task);}catch{if(this.titleSync===key)this.titleSync=null;}}
 connectionError(error){clearInterval(this.handshake);clearTimeout(this.connectTimeout);this.connectionState('error',error.message||'原生 DSH 连接失败');}
 ping(){this.frame.contentWindow?.postMessage({type:'mandifuel-native-ping'},location.origin);}
 navigate(){const target=this.current?.nativeSessionId?this.current:this.defaultTask,sid=target?.nativeSessionId;if(!this.ready||!sid)return;if(sid===this.frame.dataset.activeSession){this.pendingSession=null;return;}if(sid===this.pendingSession)return;this.pendingSession=sid;this.frame.contentWindow.postMessage({type:'mandifuel-native-select',sessionId:sid,workspaceId:target.nativeWorkspaceId},location.origin);}
 async request(path){const r=await fetch(BASE+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Workbench-Token':this.token},body:'{}'});let snapshot;try{snapshot=await r.json();}catch{throw new Error('原生 DSH 登录已失效，请从终端打印的工作台链接重新打开。');}if(!r.ok)throw new Error(snapshot.error||'原生工作区准备失败');return snapshot;}
 async bootstrap(){const snapshot=await this.request('/api/bootstrap');this.defaultTask=snapshot.task;this.watchDraft(snapshot.task);this.navigate();return snapshot.task;}
 async newTask(){if(this.creating)return;this.creating=true;$('new-task-button').disabled=true;try{this.selection++;this.events?.close();this.events=null;this.current=null;this.pendingSession='preparing-new-task';this.cb.onDraft();this.toggle(true);await this.bootstrap();}finally{if(this.pendingSession==='preparing-new-task')this.pendingSession=null;this.creating=false;$('new-task-button').disabled=false;}}
 watchDraft(task){if(this.defaultWatchId===task.id)return;this.defaultEvents?.close();this.defaultWatchId=task.id;this.defaultEvents=new EventSource(`${BASE}/api/tasks/${task.id}/stream`);const update=meta=>{if(!this.receive(meta))return;if(meta.nativeSessionId&&!meta.draft&&meta.id!==this.current?.id&&([meta.nativeSessionId,...(meta.nativeSessionIds||[])].includes(this.selectedNativeSession)||this.pendingSession===meta.nativeSessionId))this.cb.selectTask(meta.id);};this.defaultEvents.addEventListener('snapshot',event=>update(JSON.parse(event.data).task));this.defaultEvents.addEventListener('state',event=>update(JSON.parse(event.data)));}
 async init(){this.sync();try{const r=await fetch(BASE+'/api/runtime',{credentials:'same-origin'});if(!r.ok)throw new Error('请从终端打印的工作台登录链接重新打开。');const config=await r.json();if(config.protocol!==7)throw new Error('工作台服务版本已更新，请重启 frontend/server.py 后打开新的启动链接。');this.token=config.token;await this.connect();}catch(error){this.connectionError(error);throw error;}}
 async connect(){this.ready=false;this.frame.dataset.activeSession='';this.pendingSession=null;clearInterval(this.handshake);clearTimeout(this.connectTimeout);this.connectionState('loading');
  const r=await fetch('/',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(12000)});if(r.status===401||r.status===403)throw new Error('原生 DSH 登录已失效，请从终端打印的工作台链接重新打开。');if(!r.ok)throw new Error(`原生 DSH 页面加载失败（${r.status}），请重新连接。`);if(!(await r.text()).includes('__DSH_BOOT__'))throw new Error('当前端口不是原生 DSH 服务，请重启工作台并打开终端打印的链接。');
  this.frame.src='/';this.handshake=setInterval(()=>this.ping(),500);this.connectTimeout=setTimeout(()=>this.connectionError(new Error('原生 DSH 尚未连接，请重新连接。')),30000);
 }
 async retry(){try{await this.init();await this.cb.onReconnect();}catch(error){this.connectionError(error);}}
 sync(){const dialog=$('dsh-window'),mobile=this.media.matches;$('workspace-body').classList.toggle('chat-open',this.open&&!mobile);this.moving=true;if(dialog.open&&(!this.open||dialog.matches(':modal')))dialog.close();if(this.open&&!dialog.open)dialog.show();const visible=dialog.open;$('conversation-column').hidden=!visible;$('dsh-button').setAttribute('aria-expanded',String(visible));$('dsh-button').setAttribute('aria-pressed',String(visible));$('dsh-button').setAttribute('aria-label',visible?'收起 DSH 对话':'打开 DSH 对话');this.moving=false;window.dispatchEvent(new Event('workbench-layout'));}
 toggle(value=!this.open){this.open=value;this.sync();}
 async select(task){const selection=++this.selection;this.events?.close();this.events=null;this.current=task;this.navigate();const r=await fetch(`${BASE}/api/tasks/${task.id}`,{cache:'no-store'}),snapshot=await r.json();if(!r.ok)throw new Error(snapshot.error);if(selection!==this.selection)return null;if(!this.receive(snapshot.task))this.current=this.snapshots.get(task.id);this.navigate();
  this.events=new EventSource(`${BASE}/api/tasks/${task.id}/stream`);this.events.addEventListener('snapshot',event=>{if(selection!==this.selection)return;this.receive(JSON.parse(event.data).task);});this.events.addEventListener('state',event=>{if(selection!==this.selection)return;if(this.receive(JSON.parse(event.data))&&this.current.resultReady)this.cb.onResult({ready:true});});this.events.addEventListener('error',()=>{if(selection===this.selection)this.reconcile();});
  this.reconcileTimer??=setInterval(()=>this.reconcile(),5000);return snapshot;
 }
}
