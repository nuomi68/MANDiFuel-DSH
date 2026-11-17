import {paletteBytes} from './render-style.js';
export const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const format=value=>typeof value==='number'?(Math.abs(value)>0&&Math.abs(value)<.001||Math.abs(value)>=1e5?value.toExponential(3):Number(value.toPrecision(6)).toString()):String(value??'—');
export const CHART_TYPES=new Set(['chart','lineChart','scatterChart','barChart','intervalChart','heatmapChart']);
const finite=v=>typeof v==='number'&&Number.isFinite(v),colors=['#2563a6','#d1872c','#248f7b','#8b66b2','#be5268','#578fa3','#9c6644','#7e9b35','#d65d8d','#52657b','#b7a232','#805878'],dash=v=>v==='dash'?'7 4':v==='dot'?'2 4':'';
const text=(x,y,value,anchor='middle',extra='')=>`<text x="${x}" y="${y}" text-anchor="${anchor}" ${extra}>${escape(value)}</text>`;
function marker(shape,x,y,size,color,extra=''){
 const common=`fill="${escape(color)}" stroke="${escape(color)}" ${extra}`;
 if(shape==='none')return'';
 if(shape==='square')return`<rect x="${x-size}" y="${y-size}" width="${size*2}" height="${size*2}" ${common}/>`;
 if(shape==='triangle')return`<path d="M${x} ${y-size*1.25}L${x+size*1.15} ${y+size}H${x-size*1.15}Z" ${common}/>`;
 if(shape==='diamond')return`<path d="M${x} ${y-size*1.4}L${x+size} ${y}L${x} ${y+size*1.4}L${x-size} ${y}Z" ${common}/>`;
 return`<circle cx="${x}" cy="${y}" r="${size}" ${common}/>`;
}
function axis(values,spec={},categories=[]){
 const log=spec.scale==='log';if(categories.length&&log)throw new Error('分类坐标不能使用对数轴');
 const valid=values.filter(finite);if(!valid.length)throw new Error('图表中没有有效的数值点，请检查坐标列');
 if(log&&valid.some(v=>v<=0))throw new Error('对数轴要求所有有效数据及参考值为正数');
 let lo=spec.min??valid.reduce((a,b)=>Math.min(a,b),Infinity),hi=spec.max??valid.reduce((a,b)=>Math.max(a,b),-Infinity);if(!finite(lo)||!finite(hi)||log&&(lo<=0||hi<=0))throw new Error('坐标轴边界无效');
 if(hi===lo){if(log){lo/=1.2;hi*=1.2;}else{const p=Math.abs(lo)*.05||.5;lo-=p;hi+=p;}}
 if(hi<lo)throw new Error('坐标轴下限须小于上限');
 let a=log?Math.log10(lo):lo,b=log?Math.log10(hi):hi;
 if(!categories.length){const pad=(b-a)*.05;if(spec.min===undefined)a-=pad;if(spec.max===undefined)b+=pad;}
 const fraction=v=>{if(log&&v<=0)throw new Error('对数轴不允许非正数');let n=((log?Math.log10(v):v)-a)/(b-a);return spec.reverse?1-n:n;};
 let ticks=categories.length?categories.map((label,i)=>({value:i,label})):[];
 if(!ticks.length&&log){const start=Math.ceil(a),end=Math.floor(b);if(end-start>=1){for(let p=start;p<=end;p+=Math.max(1,Math.ceil((end-start)/5)))ticks.push({value:10**p,label:format(10**p)});}}
 if(spec.ticks){if(categories.length)throw new Error('分类轴使用数据标签，不接受数值刻度');if(log&&spec.ticks.some(v=>v<=0))throw new Error('对数刻度必须为正数');ticks=spec.ticks.map(value=>({value,label:format(value)}));}
 if(!ticks.length&&!log){const raw=(b-a)/4,magnitude=10**Math.floor(Math.log10(raw)),n=raw/magnitude,step=(n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*magnitude;for(let value=Math.ceil(a/step)*step;value<=b+step*1e-8;value+=step)ticks.push({value,label:format(Number(value.toPrecision(10)))});}
 if(!ticks.length)ticks=Array.from({length:5},(_,i)=>{const v=log?10**(a+(b-a)*i/4):a+(b-a)*i/4;return{value:v,label:format(v)};});
 return{fraction,ticks,low:log?10**a:a,high:log?10**b:b};
}
function legendSVG(entries,node,width,base,ink){
 if(node.legend==='none')return{markup:'',height:base+8};
 const open=(entry,x,y,w)=>`<g data-chart-legend="${entry.key}" role="button" tabindex="0" aria-label="${escape(entry.label)}" aria-pressed="${!entry.hidden}" opacity="${entry.hidden ? .35 : 1}"><rect x="${x-4}" y="${y-15}" width="${w}" height="22" fill="transparent"/>`;
 if(node.legend==='right'&&width>=600){let y=33,markup='';const x=width-174;for(const entry of entries){markup+=open(entry,x,y,170);markup+=entry.band?`<rect x="${x}" y="${y-8}" width="22" height="11" fill="${escape(entry.color)}" opacity=".3"/>`:`<path d="M${x} ${y-2}h24" stroke="${escape(entry.color)}" stroke-width="2" stroke-dasharray="${dash(entry.dash)}"/>`+marker(entry.marker||'none',x+12,y-2,3,entry.color);markup+=text(x+30,y+2,entry.label,'start',`fill="${escape(ink)}"`);markup+='</g>';y+=23;}return{markup,height:Math.max(base+8,y+8)};}
 let x=16,y=base+13,markup='';
 for(const entry of entries){const length=Math.min(width-24,Math.max(110,entry.label.length*12+48));if(x+length>width-8&&x>16){x=16;y+=25;}
  markup+=open(entry,x,y,length);markup+=entry.band?`<rect x="${x}" y="${y-8}" width="22" height="11" fill="${escape(entry.color)}" opacity=".3"/>`:`<path d="M${x} ${y-2}h24" stroke="${escape(entry.color)}" stroke-width="2" stroke-dasharray="${dash(entry.dash)}"/>`+marker(entry.marker||'none',x+12,y-2,3,entry.color);
  markup+=text(x+30,y+2,entry.label,'start',`fill="${escape(ink)}"`)+'</g>';x+=length;
 }
 return{markup,height:y+19};
}
function frame(node,table,theme,width,height,body,legend,labels,attributes=''){
 const ink=theme.ink||'#374151',caption=node.caption||table?.note||'',extra=caption?text(16,legend.height+14,caption.length>110?caption.slice(0,107)+'…':caption,'start','font-size="10"'):'';
 return`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${legend.height+(caption?29:0)}" role="group" aria-label="${escape(node.title||'分析图')}" font-family="Workbench CJK,system-ui,sans-serif" font-size="12" font-weight="400" stroke="none" fill="${escape(ink)}" ${attributes}><title>${escape(node.title||'分析图')}</title>${body}${labels}${legend.markup}${extra}</svg>`;
}

export function chartSVG(node,series,theme={},viewportWidth=720,runtime={}){
 if(node.type==='heatmapChart')return heatmapSVG(node,series[0]?.table,theme,viewportWidth);
 const width=Math.max(280,viewportWidth),height=node.height||330,left=width<420?70:86,right=width-(node.legend==='right'&&width>=600?196:22),top=24,bottom=height-65,grid=theme.line||'#e5e7eb';
 const defaultMark={scatterChart:'scatter',barChart:'bar',intervalChart:'interval'}[node.type]||'line',entries=[];let categories=[],xs=[],ys=[],units=new Set(),xunits=new Set(),total=0;
 const prepared=series.map((s,i)=>{
  const mark=s.mark||defaultMark,x=s.x||'x',y=s.y||'value',needed=[...(s.xLow?[s.xLow,s.xHigh]:[x]),...(s.yLow?[s.yLow,s.yHigh]:[y])];
  if(needed.some(key=>!s.table.columns.some(c=>c.id===key)))throw new Error('图表引用不存在的坐标列');
  const unit=s.table.columns.find(c=>c.id===(s.y||s.yLow||'value'))?.unit;if(unit)units.add(unit);const xunit=s.table.columns.find(c=>c.id===(s.x||s.xLow||'x'))?.unit;if(xunit)xunits.add(xunit);
  total+=s.table.rows.length;if(total>50000)throw new Error('单图超过 50000 个数据点，请分组展示');
  const points=s.table.rows.map((row,rowIndex)=>{
   const xlo=s.xLow?row[s.xLow]:undefined,xhi=s.xHigh?row[s.xHigh]:undefined,ylo=s.yLow?row[s.yLow]:undefined,yhi=s.yHigh?row[s.yHigh]:undefined;
   if(s.xLow&&(!finite(xlo)||!finite(xhi))||s.yLow&&(!finite(ylo)||!finite(yhi)))return null;
   if(s.xLow&&xlo>xhi||s.yLow&&ylo>yhi)throw new Error('区间下限不能大于上限');
   const xv=s.xLow&&!Object.hasOwn(row,x)?(xlo+xhi)/2:row[x],yv=s.yLow&&!Object.hasOwn(row,y)?(ylo+yhi)/2:row[y];
   if((!finite(xv)&&typeof xv!=='string')||!finite(yv))return null;
   if(typeof xv==='string'&&!categories.includes(xv))categories.push(xv);
   return{x:xv,y:yv,xlo,xhi,ylo,yhi,row,rowIndex};
  });
  const color=s.color||colors[i%colors.length],shape=s.marker||(mark==='scatter'?'circle':'none'),hidden=runtime.hidden?.has('series:'+i);entries.push({label:s.label,color,dash:s.dash,marker:shape,key:'series:'+i,hidden});return{...s,mark,color,shape,points,seriesIndex:i,hidden};
 });
 if(units.size>1||xunits.size>1)throw new Error('同一数值轴含不同单位，请分图展示');
 for(const s of prepared)for(const p of s.points)if(p){if(categories.length&&typeof p.x!=='string')throw new Error('同一横轴不能混用分类和数值坐标');p.plotX=categories.length?categories.indexOf(p.x):p.x;xs.push(p.plotX,...(p.xlo!==undefined?[p.xlo,p.xhi]:[]));ys.push(p.y,...(p.ylo!==undefined?[p.ylo,p.yhi]:[]));}
 if(!xs.length)throw new Error('图表中没有有效的数值点，请检查坐标列');
 if(prepared.some(s=>s.mark==='bar')&&node.yAxis?.scale!=='log')ys.push(0);
 for(const[i,ref]of(node.references||[]).entries()){(ref.axis==='x'?xs:ys).push(...(ref.value!==undefined?[ref.value]:[ref.from,ref.to]));entries.push({label:ref.label||'',color:ref.color||'#64748b',dash:ref.dash||'dash',band:ref.value===undefined,key:'ref:'+i,hidden:runtime.hidden?.has('ref:'+i)});}
 const spec=(key)=>({...node[key+'Axis'],...(runtime.viewport?.[key]?{min:runtime.viewport[key][0],max:runtime.viewport[key][1]}:{})}),ax=axis(xs,spec('x'),categories),ay=axis(ys,spec('y')),px=v=>left+ax.fraction(v)*(right-left),py=v=>bottom-ay.fraction(v)*(bottom-top),clip=`plot-${String(node.id||'chart').replace(/[^A-Za-z0-9_-]/g,'')}`;
 let body=`<defs><clipPath id="${clip}"><rect x="${left}" y="${top}" width="${right-left}" height="${bottom-top}"/></clipPath></defs>`;
 const xTicks=ax.ticks.filter((_,i)=>i%Math.max(1,Math.ceil(ax.ticks.length/(width<420?4:8)))===0);
 for(const tick of ay.ticks){const y=py(tick.value);if(node.yAxis?.grid!==false)body+=`<path d="M${left} ${y}H${right}" stroke="${escape(grid)}"/>`;body+=text(left-8,y+4,tick.label,'end');}
 for(const [tickIndex,tick] of xTicks.entries()){const x=px(tick.value);if(node.xAxis?.grid)body+=`<path d="M${x} ${top}V${bottom}" stroke="${escape(grid)}"/>`;body+=text(x,bottom+20,tick.label,tickIndex===0?'start':tickIndex===xTicks.length-1?'end':'middle');}
 body+=`<path d="M${left} ${top}V${bottom}H${right}" fill="none" stroke="${escape(grid)}"/><g clip-path="url(#${clip})">`;
 for(const[i,ref]of(node.references||[]).entries()){if(runtime.hidden?.has('ref:'+i))continue;const c=ref.color||'#64748b',vertical=ref.axis==='x',pos=vertical?px:py;
  if(ref.value!==undefined)body+=`<path d="${vertical?'M'+pos(ref.value)+' '+top+'V'+bottom:'M'+left+' '+pos(ref.value)+'H'+right}" stroke="${escape(c)}" stroke-width="1.5" stroke-dasharray="${dash(ref.dash||'dash')}" fill="none"><title>${escape(ref.label||format(ref.value))}</title></path>`;
  else{const a=pos(ref.from),b=pos(ref.to);body+=`<rect x="${vertical?Math.min(a,b):left}" y="${vertical?top:Math.min(a,b)}" width="${vertical?Math.abs(b-a):right-left}" height="${vertical?bottom-top:Math.abs(b-a)}" fill="${escape(c)}" opacity="${ref.opacity??.13}"><title>${escape(ref.label||'容差带')}: ${ref.from}–${ref.to}</title></rect>`;}
 }
 for(const s of prepared){
  if(s.hidden)continue;
  const points=s.order==='x'?s.points.filter(Boolean).slice().sort((a,b)=>a.plotX-b.plotX):s.points;
  if(s.mark==='line'){let previous=null,path='';for(const p of points){if(!p){previous=null;continue;}const x=px(p.plotX),y=py(p.y);path+=previous?(s.step?`H${x}V${y}`:`L${x} ${y}`):`M${x} ${y}`;previous=p;}body+=`<path d="${path}" fill="none" stroke="${escape(s.color)}" stroke-width="${s.width||2}" stroke-dasharray="${dash(s.dash)}" opacity="${s.opacity??1}"><title>${escape(s.label)}</title></path>`;}
  const barSeries=prepared.filter(entry=>entry.mark==='bar'),barCount=Math.max(1,barSeries.length),barWidth=Math.max(2,Math.min(72,(right-left)/Math.max(1,points.filter(Boolean).length)*.65)/barCount),barOffset=(barSeries.indexOf(s)-(barCount-1)/2)*barWidth;
  for(const p of points){if(!p)continue;const x=px(p.plotX),y=py(p.y),meta=p.row.runId?` data-chart-run="${escape(p.row.runId)}" role="button"`:'',label=`${s.label}: ${p.x}, ${format(p.y)}${p.xlo!==undefined?' ['+p.xlo+', '+p.xhi+']':''}${p.ylo!==undefined?' ['+p.ylo+', '+p.yhi+']':''}`;
   body+=`<g opacity="${s.opacity??1}" data-chart-point="${s.seriesIndex}:${p.rowIndex}" tabindex="0" aria-label="${escape(label)}"${meta}><title>${escape(label)}</title>`;
   body+=`<circle cx="${x}" cy="${y}" r="11" fill="transparent" stroke="none"/><circle class="chart-selection-ring" cx="${x}" cy="${y}" r="8" fill="none" stroke="${escape(theme.accent||'#4f46e5')}" stroke-width="2"/>`;
   if(s.mark==='bar'){const base=py(node.yAxis?.scale==='log'?ay.low:0);body+=`<rect x="${x+barOffset-barWidth/2}" y="${Math.min(y,base)}" width="${barWidth}" height="${Math.max(1,Math.abs(y-base))}" fill="${escape(s.color)}"/>`;}
   if(s.mark==='interval'){
    if(p.xlo!==undefined){const a=px(p.xlo),b=px(p.xhi);body+=`<path d="M${a} ${y}H${b}" fill="none" stroke="transparent" stroke-width="16"/><path d="M${a} ${y}H${b}M${a} ${y-5}V${y+5}M${b} ${y-5}V${y+5}" fill="none" stroke="${escape(s.color)}" stroke-width="${s.width||2}"/>`;}
    if(p.ylo!==undefined){const a=py(p.ylo),b=py(p.yhi);body+=`<path d="M${x} ${a}V${b}" fill="none" stroke="transparent" stroke-width="16"/><path d="M${x} ${a}V${b}M${x-5} ${a}H${x+5}M${x-5} ${b}H${x+5}" fill="none" stroke="${escape(s.color)}" stroke-width="${s.width||2}"/>`;}
   }
   body+=marker(s.shape,x,y,s.size||3.5,s.color)+`</g>`;
  }
 }
 body+='</g>';
 const first=series[0],axisLabel=c=>c?(c.label||c.id)+(c.unit?' ['+c.unit+']':''):'',xcol=first.table.columns.find(c=>c.id===(first.x||first.xLow||'x')),ycol=first.table.columns.find(c=>c.id===(first.y||first.yLow||'value'));
 const labels=text((left+right)/2,height-19,node.xAxis?.label||node.xLabel||axisLabel(xcol))+`<text transform="translate(17 ${(top+bottom)/2}) rotate(-90)" text-anchor="middle">${escape(node.yAxis?.label||node.yLabel||axisLabel(ycol))}</text>`;
 const domain={x:{min:ax.low,max:ax.high,scale:node.xAxis?.scale||'linear',reverse:!!node.xAxis?.reverse,category:!!categories.length},y:{min:ay.low,max:ay.high,scale:node.yAxis?.scale||'linear',reverse:!!node.yAxis?.reverse}},attributes=`data-chart-domain="${escape(JSON.stringify(domain))}" data-chart-plot="${left},${top},${right},${bottom}"`;
 const legend=legendSVG(entries.filter(e=>e.label),node,width,height-2,theme.ink||'#374151');return frame(node,null,theme,width,height,body,legend,labels,attributes);
}

export function heatmapSVG(node,table,theme={},viewportWidth=720){
 if(!table?.rows?.length)throw new Error('热图没有真实数据');
 const ids=table.columns.map(c=>c.id);for(const key of [node.x,node.y,node.value])if(!ids.includes(key))throw new Error('热图引用不存在的数据列');
 const xs=[...new Set(table.rows.map(r=>r[node.x]).filter(v=>finite(v)||typeof v==='string'))],ys=[...new Set(table.rows.map(r=>r[node.y]).filter(v=>finite(v)||typeof v==='string'))];
 if(!xs.length||!ys.length||xs.length*ys.length>20000)throw new Error('热图网格为空或超出 20000 格');
 for(const values of [xs,ys]){if(values.every(finite))values.sort((a,b)=>a-b);else if(values.some(finite))throw new Error('热图坐标类型不能混用');}
 const cells=new Map(),cellRows=new Map(),values=[];for(const[i,row]of table.rows.entries()){const key=JSON.stringify([row[node.x],row[node.y]]);if(cells.has(key))throw new Error('热图同一坐标有重复值，请先明确分组或聚合规则');cells.set(key,row[node.value]);cellRows.set(key,i);if(row[node.value]!=null&&!finite(row[node.value]))throw new Error('热图数值列必须是有限数字或缺失');if(finite(row[node.value]))values.push(row[node.value]);}
 if(!values.length)throw new Error('热图没有有效数值');let[lo,hi]=node.colorRange||[Math.min(...values),Math.max(...values)];const uniform=lo===hi,constant=lo;if(uniform){lo-=Math.abs(lo)*.01||.5;hi+=Math.abs(hi)*.01||.5;}
 const width=Math.max(280,viewportWidth),height=node.height||330,left=72,right=width-88,top=20,bottom=height-62,colors=paletteBytes(node.palette||'viridis');
 const positions=(list,spec,a,b)=>{
  const numeric=list.every(finite),log=spec?.scale==='log';if(log&&(!numeric||list.some(v=>v<=0)))throw new Error('对数轴要求有效坐标为正数');
  const edges=numeric?list.map((v,i)=>log?[i?Math.sqrt(v*list[i-1]):v/Math.sqrt((list[1]||v*1.5)/v),i<list.length-1?Math.sqrt(v*list[i+1]):v*Math.sqrt(v/(list[i-1]||v/1.5))]:[i?(v+list[i-1])/2:v-(list[1]===undefined?.5:(list[1]-v)/2),i<list.length-1?(v+list[i+1])/2:v+(list[i-1]===undefined?.5:(v-list[i-1])/2)]):list.map((_,i)=>[i-.5,i+.5]);
  const domain=axis(edges.flat(),{...spec,min:spec?.min??edges[0][0],max:spec?.max??edges.at(-1)[1]}),project=v=>a+domain.fraction(v)*(b-a);
  if(!numeric&&spec?.ticks)throw new Error('分类热图使用实际分类刻度');
  return{numeric,project,at:i=>edges[i].map(project),ticks:(spec?.ticks||list).map((v,i)=>({value:v,at:project(numeric?v:i)}))};
 };
 const ax=positions(xs,node.xAxis,left,right),ay=positions(ys,node.yAxis,bottom,top);let body='';
 for(const[i,xv]of xs.entries())for(const[j,yv]of ys.entries()){
  const [a,b]=ax.at(i),[c,d]=ay.at(j),x=Math.min(a,b),y=Math.min(c,d),w=Math.abs(b-a),h=Math.abs(d-c),value=cells.get(JSON.stringify([xv,yv]));let fill=theme.panel||'#ffffff',ink=theme.ink||'#374151';
  if(finite(value)){const n=Math.round(Math.max(0,Math.min(1,(value-lo)/(hi-lo)))*255)*4,rgb=[...colors.slice(n,n+3)];fill=`rgb(${rgb.join(',')})`;ink=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722<135?'#ffffff':'#1f2937';}
  const index=cellRows.get(JSON.stringify([xv,yv])),row=table.rows[index],meta=row?` data-chart-point="0:${index}" tabindex="0"${row.runId?` data-chart-run="${escape(row.runId)}" role="button"`:''}`:'';
  body+=`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="${escape(theme.line||'#ffffff')}" stroke-width=".6" data-value="${finite(value)?value:'missing'}"${meta}><title>${escape(xv)}, ${escape(yv)}: ${finite(value)?format(value):'缺失'}</title></rect>`;
  if(!finite(value))body+=`<path d="M${x} ${y+h}L${x+w} ${y}" stroke="${escape(theme.line||'#d1d5db')}"/>`;
  if(node.showValues!==false&&w>35&&h>22)body+=text(x+w/2,y+h/2+4,finite(value)?node.valueDigits!==undefined?value.toFixed(node.valueDigits):format(value):'—','middle',`fill="${ink}"`);
 }
 for(const axis of [ax,ay])for(const[i,t]of axis.ticks.entries())if(i%Math.max(1,Math.ceil(axis.ticks.length/8))===0)body+=axis===ax?text(t.at,bottom+20,t.value):text(left-8,t.at+4,t.value,'end');
 for(const ref of node.references||[]){const axis=ref.axis==='x'?ax:ay;if(!axis.numeric)throw new Error('分类热图不支持数值参考线');const f=axis.project,c=ref.color||'#64748b';if(ref.value!==undefined){const p=f(ref.value);if(ref.axis==='x'&&p>=left&&p<=right||ref.axis==='y'&&p>=top&&p<=bottom)body+=`<path d="${ref.axis==='x'?'M'+p+' '+top+'V'+bottom:'M'+left+' '+p+'H'+right}" fill="none" stroke="${escape(c)}" stroke-width="1.5" stroke-dasharray="${dash(ref.dash||'dash')}"><title>${escape(ref.label||'参考线')}</title></path>`;}else{const a=f(ref.from),b=f(ref.to),vertical=ref.axis==='x',start=Math.max(vertical?left:top,Math.min(a,b)),end=Math.min(vertical?right:bottom,Math.max(a,b));if(end>start)body+=`<rect x="${vertical?start:left}" y="${vertical?top:start}" width="${vertical?end-start:right-left}" height="${vertical?bottom-top:end-start}" fill="${escape(c)}" opacity="${ref.opacity??.15}"><title>${escape(ref.label||'参考区间')}</title></rect>`;}}
 for(let i=0;i<128;i++){const k=(uniform?128:Math.round((127-i)/127*255))*4;body+=`<rect x="${right+20}" y="${top+(bottom-top)*i/128}" width="13" height="${(bottom-top)/128+1}" fill="rgb(${[...colors.slice(k,k+3)].join(',')})"/>`;}
 body+=text(right+39,top+5,format(uniform?constant:hi),'start','font-size="10"')+text(right+39,bottom,format(uniform?constant:lo),'start','font-size="10"');const label=id=>{const c=table.columns.find(c=>c.id===id);return(c.label||c.id)+(c.unit?' ['+c.unit+']':'');};
 const labels=text((left+right)/2,height-14,node.xAxis?.label||node.xLabel||label(node.x))+`<text transform="translate(16 ${(top+bottom)/2}) rotate(-90)" text-anchor="middle">${escape(node.yAxis?.label||node.yLabel||label(node.y))}</text>`+text(right+26,bottom+20,table.columns.find(c=>c.id===node.value)?.unit||'');
 return frame(node,{note:uniform?'有效网格均为 '+format(constant)+'；空格表示缺失数据':'离散采样网格；空格表示缺失数据'},theme,width,height,body,{markup:'',height},labels);
}

export function tableColumns(table,node={}){
 const columns=(node.columns||table.columns.map(c=>c.id)).map(spec=>{const id=typeof spec==='string'?spec:spec.id,base=table.columns.find(c=>c.id===id);if(!base)throw new Error('表格引用不存在的数据列');return{...base,...(typeof spec==='string'?{}:spec)};});
 for(const key of [node.sort?.column,node.highlight?.column].filter(Boolean))if(!table.columns.some(c=>c.id===key))throw new Error('表格排序或突出显示引用不存在的数据列');return columns;
}
export function tableRows(table,{query='',sort}={}){
 let rows=table.rows.filter(row=>!query||Object.values(row).some(value=>String(value??'').toLocaleLowerCase().includes(query.toLocaleLowerCase())));
 if(sort)rows=rows.slice().sort((a,b)=>{const x=a[sort.column],y=b[sort.column];if(x==null||y==null)return x==null?(y==null?0:1):-1;const n=finite(x)&&finite(y)?x-y:String(x).localeCompare(String(y),'zh-CN',{numeric:true});return sort.direction==='desc'?-n:n;});return rows;
}
export function formatCell(value,column={}){if(value==null)return'—';if(!finite(value))return String(value);if(column.format==='fixed')return value.toFixed(column.digits??3);if(column.format==='scientific')return value.toExponential(column.digits??3);return format(value);}
export function chartDataTable(series){
 const columns=new Map();for(const s of series)for(const c of s.table.columns)if(!columns.has(c.id))columns.set(c.id,c);
 let key='series';while(columns.has(key))key='_'+key;
 return{columns:[{id:key,label:'曲线'},...columns.values()],rows:series.flatMap(s=>s.table.rows.map(row=>({...row,[key]:s.label})))};
}
export function tableCSV(table){const columns=table.columns.map(c=>c.id),quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';return'\uFEFF'+[columns.map(quote).join(','),...table.rows.map(row=>columns.map(c=>quote(row[c])).join(','))].join('\r\n');}
