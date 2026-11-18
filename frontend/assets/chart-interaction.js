import {format} from './chart-view.js';
import {centeredZoom,zoomViewport,nearestChartPoint} from './chart-navigation.js';

const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
export class ChartInteraction{
 constructor(entry,{paint,select,getStudy}){
  Object.assign(this,{entry,paint,select,getStudy});this.hidden=new Set();this.viewport=null;this.zoomMode=false;
  const body=entry.body;
  body.addEventListener('pointermove',e=>this.move(e));
  body.addEventListener('pointerleave',()=>{if(!this.pinned)this.hideTip();});
  body.addEventListener('focusin',e=>{const point=e.target.closest('[data-chart-point]');if(point)this.showTip(point);});
  body.addEventListener('focusout',()=>{if(!this.pinned)this.hideTip();});
  body.addEventListener('click',e=>this.click(e));
  body.addEventListener('keydown',e=>{if(e.key==='Escape'){this.pinned=null;this.hideTip();this.setZoomMode(false);}else if(['Enter',' '].includes(e.key)&&e.target.closest('[data-chart-point],[data-chart-legend]')){e.preventDefault();this.click(e);}});
  body.addEventListener('dblclick',e=>{const run=e.target.closest('[data-chart-run]');if(run)this.select(run.dataset.chartRun,true);else this.reset();});
  body.addEventListener('pointerdown',e=>this.down(e));
  body.addEventListener('pointerup',e=>this.up(e));
  body.addEventListener('pointercancel',()=>this.cancelDrag());
  body.addEventListener('wheel',e=>{if(!e.ctrlKey||!this.domain())return;e.preventDefault();this.viewport=centeredZoom(this.domain(),e.deltaY<0?.8:1.25);this.repaint();},{passive:false});
 }
 get svg(){return this.entry.body.querySelector('svg');}
 domain(){const value=this.svg?.dataset.chartDomain;return value?JSON.parse(value):null;}
 toolbar(){
  const bar=el('div','adaptive-chart-tools');
  const button=(text,label,action)=>{const b=el('button','',text);b.type='button';b.title=label;b.setAttribute('aria-label',label);b.addEventListener('click',action);bar.append(b);return b;};
  if(this.entry.node.type!=='heatmapChart'){
   button('＋','放大图表',()=>{const d=this.domain();if(d){this.viewport=centeredZoom(d,.65);this.repaint();}});
   this.brushButton=button('框选','框选区域缩放',()=>this.setZoomMode(!this.zoomMode));this.brushButton.setAttribute('aria-pressed','false');
   this.resetButton=button('复位','恢复完整数据范围',()=>this.reset());this.resetButton.disabled=true;
  }
  button('全屏','全屏查看图表',async()=>{try{if(document.fullscreenElement===this.entry.element)await document.exitFullscreen();else await this.entry.element.requestFullscreen();}catch{/* Browser may deny fullscreen; the normal chart remains usable. */}});
  return bar;
 }
 setZoomMode(value){this.zoomMode=value;this.entry.body.dataset.zoomMode=String(value);this.brushButton?.setAttribute('aria-pressed',String(value));if(value){this.pinned=null;this.hideTip();}}
 reset(){this.viewport=null;this.pinned=null;this.setZoomMode(false);this.repaint();}
 repaint(){this.hideTip();this.paint();if(this.resetButton)this.resetButton.disabled=!this.viewport;}
 afterPaint(){this.tip=null;this.pointLocations=[...this.entry.body.querySelectorAll('[data-chart-point][data-point-x]')].map(element=>({element,x:Number(element.dataset.pointX),y:Number(element.dataset.pointY)}));if(this.brushButton)this.brushButton.disabled=!this.domain();}
 pointAt(event){
  const direct=event.target.closest('[data-chart-point]'),matrix=this.svg?.getScreenCTM();
  if(!event.clientX||!matrix||!this.pointLocations?.length)return direct;
  const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
  return nearestChartPoint(this.pointLocations,p.x,p.y)?.element||direct;
 }
 showTip(point,event){
  const [si,ri]=point.dataset.chartPoint.split(':').map(Number),s=this.entry.series?.[si],row=s?.table.rows[ri];if(!row)return;
  const run=this.getStudy()?.runs.find(r=>r.id===row.runId),tip=this.tip||el('div','adaptive-chart-tooltip');this.tip=tip;tip.setAttribute('role','tooltip');tip.replaceChildren();
  tip.append(el('strong','',run?(run.label||run.id):s.label||this.entry.node.title||'采样值'));
  const keys=this.entry.node.type==='heatmapChart'?[this.entry.node.x,this.entry.node.y,this.entry.node.value]:[s.x||(!s.xLow?'x':null),s.xLow,s.xHigh,s.y||(!s.yLow?'value':null),s.yLow,s.yHigh];
  const list=el('dl');for(const key of [...new Set(keys.filter(Boolean))]){const c=s.table.columns.find(c=>c.id===key);if(!c)continue;list.append(el('dt','',c.label||c.id),el('dd','',format(row[key])+(c.unit?' '+c.unit:'')));}tip.append(list);
  if(run)tip.append(el('small','',run.viewIds?.length?'点击选中 · 双击查看模型':'点击选中工况'));
  this.entry.body.append(tip);const box=this.entry.body.getBoundingClientRect(),p=point.getBoundingClientRect(),x=event?.clientX??p.x+p.width/2,y=event?.clientY??p.y+p.height/2;
  tip.style.left=clamp(x-box.x+14,4,Math.max(4,box.width-tip.offsetWidth-4))+'px';tip.style.top=clamp(y-box.y+14,4,Math.max(4,box.height-tip.offsetHeight-4))+'px';
  this.entry.body.querySelectorAll('[data-hovered]').forEach(n=>n.removeAttribute('data-hovered'));point.setAttribute('data-hovered','true');
 }
 hideTip(){this.tip?.remove();this.tip=null;this.entry.body.querySelectorAll('[data-hovered]').forEach(n=>n.removeAttribute('data-hovered'));}
 click(e){
  if(this.suppressClick){this.suppressClick=false;return;}
  const legend=e.target.closest('[data-chart-legend]');if(legend){const key=legend.dataset.chartLegend;this.hidden.has(key)?this.hidden.delete(key):this.hidden.add(key);const focused=document.activeElement===legend;this.repaint();if(focused)this.svg.querySelector(`[data-chart-legend="${key}"]`)?.focus();return;}
  const point=this.pointAt(e);if(!point){this.pinned=null;this.hideTip();return;}this.pinned=point.dataset.chartPoint;this.showTip(point,e.clientX?e:undefined);const [si,ri]=point.dataset.chartPoint.split(':').map(Number),row=this.entry.series?.[si]?.table.rows[ri];if(row?.selection||point.dataset.chartRun)this.select(point.dataset.chartRun,false,row?.selection);
 }
 position(e){const svg=this.svg,m=svg?.getScreenCTM();if(!m)return;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(m.inverse()),[l,t,r,b]=svg.dataset.chartPlot.split(',').map(Number);return{x:clamp(p.x,l,r),y:clamp(p.y,t,b),l,t,r,b};}
 down(e){
  if(!this.zoomMode||e.button!==0||!this.domain()||e.target.closest('[data-chart-legend]'))return;const p=this.position(e);if(!p)return;e.preventDefault();this.entry.body.setPointerCapture(e.pointerId);this.drag={start:p,end:p,pointer:e.pointerId};
  this.brush=document.createElementNS('http://www.w3.org/2000/svg','rect');this.brush.setAttribute('class','adaptive-chart-brush');this.svg.append(this.brush);
 }
 move(e){if(this.drag){const p=this.position(e);this.drag.end=p;const a=this.drag.start;for(const[k,v]of Object.entries({x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),width:Math.abs(a.x-p.x),height:Math.abs(a.y-p.y)}))this.brush.setAttribute(k,v);return;}if(this.zoomMode)return;const point=this.pointAt(e);if(point)this.showTip(point,e);else if(!this.pinned)this.hideTip();}
 up(e){if(!this.drag)return;const{start:a,end:b}=this.drag;this.cancelDrag();if(Math.abs(a.x-b.x)<8||Math.abs(a.y-b.y)<8)return;this.suppressClick=true;this.viewport=zoomViewport(this.domain(),{x:[(a.x-a.l)/(a.r-a.l),(b.x-b.l)/(b.r-b.l)],y:[(a.b-a.y)/(a.b-a.t),(b.b-b.y)/(b.b-b.t)]});this.setZoomMode(false);this.repaint();}
 cancelDrag(){if(this.drag&&this.entry.body.hasPointerCapture(this.drag.pointer))this.entry.body.releasePointerCapture(this.drag.pointer);this.drag=null;this.brush?.remove();this.brush=null;}
}
