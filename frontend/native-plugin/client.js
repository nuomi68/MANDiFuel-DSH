window.__ModuleLoader__.load({
 id:'mandifuel-native-workbench',
 factory:()=>({
  name:'mandifuel-native-workbench',inject:['sessions'],
  apply(ctx){
   if(window.parent!==window)ctx.effect(()=>{
    // Target the native frame's public DOM markers, not generated CSS hashes.
    // Keep details and overlays mounted; only the navigation track disappears.
    const style=document.createElement('style');
    style.textContent='[data-mandifuel-embedded-frame] > :first-child{visibility:hidden!important;pointer-events:none!important;border:0!important}[data-mandifuel-embedded-frame] > [data-side="sidebar"]{display:none!important}';
    document.head.append(style);
    const frames=new Map();
    const update=()=>{for(const overlay of document.querySelectorAll('[data-shell-overlay]')){
     const frame=overlay.parentElement;if(!frame?.style.gridTemplateColumns)continue;
     if(!frames.has(frame)){frames.set(frame,frame.style.gridTemplateColumns);frame.setAttribute('data-mandifuel-embedded-frame','');}
     const columns=frame.style.gridTemplateColumns;
     const hidden=columns.replace(/^\s*[\d.]+px\s+/, '0px ');
     if(columns!==hidden){frames.set(frame,columns);frame.style.setProperty('grid-template-columns',hidden,'important');}
    }};
    const observer=new MutationObserver(update);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style']});update();
    return()=>{observer.disconnect();style.remove();for(const [frame,columns]of frames){frame.removeAttribute('data-mandifuel-embedded-frame');frame.style.gridTemplateColumns=columns;}};
   });
   const send=()=>{const state=ctx.sessions.list.getSnapshot(),entry=state.byId[state.current];if(window.parent!==window)window.parent.postMessage({type:'mandifuel-native-selected',sessionId:state.current||null,title:entry?.projectionValues?.title||null,running:!!entry?.running},location.origin);};
   const select=async event=>{if(event.origin!==location.origin||event.source!==window.parent)return;if(event.data?.type==='mandifuel-native-ping'){window.parent.postMessage({type:'mandifuel-native-ready'},location.origin);return;}if(event.data?.type!=='mandifuel-native-select')return;try{await ctx.sessions.refresh();try{ctx.sessions.open(event.data.sessionId);}catch(error){if(!event.data.workspaceId)throw error;await ctx.sessions.create({sessionId:event.data.sessionId,workspaceId:event.data.workspaceId});ctx.sessions.open(event.data.sessionId);}send();}catch(error){window.parent.postMessage({type:'mandifuel-native-error',message:String(error.message||error)},location.origin);}};
   ctx.effect(()=>{window.addEventListener('message',select);return()=>window.removeEventListener('message',select);});
   ctx.effect(()=>ctx.sessions.list.subscribe(send));
   if(window.parent!==window)window.parent.postMessage({type:'mandifuel-native-ready'},location.origin);
  }
 })
});
