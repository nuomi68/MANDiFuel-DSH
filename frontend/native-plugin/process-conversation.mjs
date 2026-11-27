// Only append-origin, visible conversation belongs in the observer's small window.
export function conversationEvent(session,event){
  if(event.surfaceOp!=='append')return;
  const data=event.data||{};
  if(event.type==='assistant/message'){
    const text=(data.message?.content||data.content||[]).filter(b=>b.type==='text').map(b=>b.text).join(' ').trim();
    if(text)return {kind:'assistant-note',text:text.slice(0,420)};
  }
  if(event.type==='tool/result'){
    const result=data.message?.content?.find(b=>b.type==='tool-result');
    if(!result)return;
    const seq=event.sourceEventSeqs?.[0];
    const tool=seq!=null?session.eventAt(seq)?.data?.name:undefined;
    const output=(result.content||[]).filter(b=>b.type==='text').map(b=>b.text).join(' ');
    const exit=output.match(/^(?:Process exited with code\s+|Exit code:\s*)(-?\d+)\b/im);
    return {kind:'tool-end',tool:tool||'工具',failed:Boolean(result.isError||data.error||exit&&Number(exit[1])!==0)};
  }
}
