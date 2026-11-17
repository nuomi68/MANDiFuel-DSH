import {compileExpression,meshContext} from './render-program.js';
import {nearestFrame,bestHistory} from './study-math.js';

export function nearestCell(mesh,point){
 const centres=mesh?.cellCenters;if(!centres?.length)throw new Error('测点需要真实单元中心');
 const axis=mesh.reconstruction?.type==='axisymmetric-revolve'?'xyz'.indexOf(mesh.reconstruction.axis):-1,radial=[0,1,2].filter(i=>i!==axis);
 let distance=Infinity,index=-1;
 for(let i=0;i<centres.length;i++){
  const c=centres[i],d=axis>=0?(Math.hypot(...radial.map(j=>c[j]))-Math.hypot(...radial.map(j=>point[j])))**2+(c[axis]-point[axis])**2:c.reduce((n,v,j)=>n+(v-point[j])**2,0);
  if(d<distance){distance=d;index=i;}
 }
 return{index,distance:Math.sqrt(distance),samplePoint:centres[index]};
}

function finiteValues(values){if(!Array.isArray(values)||!values.length||values.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw new Error('图表数据缺失或包含非有限数值');return values;}
function reduce(values,kind){finiteValues(values);if(kind==='mean')return values.reduce((a,b)=>a+b,0)/values.length;return values.reduce((a,b)=>kind==='min'?Math.min(a,b):Math.max(a,b));}
export function evaluatePosition(expressions,mesh,parameters={}){
 const bounds=meshContext(mesh),context={...bounds,x:bounds.centerX,y:bounds.centerY,z:bounds.centerZ},point=expressions.map(s=>compileExpression(s)(context,parameters));
 if(!point.every(v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e12))throw new Error('测点坐标无效');return point;
}

async function rawSource(source,context){
 if(source.kind==='study')return studyTable(await context.getStudyData(),source);
 if(source.kind==='dataset')return context.getDataset(source.dataset);
 const {data,meta}=await context.getViewData(source.view),field=source.field==='selected'?(context.state.field||meta.fields?.[0]?.id):source.field;
 const variable=meta.fields?.find(f=>f.id===field);if(!variable)throw new Error('图表引用不存在的物理量：'+field);
 if(data.kind==='mesh')throw new Error('网格预览没有结果场');
 const frames=data.frames?.length?data.frames:[{time:0,fields:data}],meshAt=frame=>data.meshes?.[frame.mesh],valuesAt=frame=>finiteValues(frame.fields?.[field]||data[field]);
 const columns=[{id:'x',label:source.kind==='profile'?'坐标':'时间',unit:source.kind==='profile'?'':meta.timeUnit||'s'},{id:'value',label:variable.label,unit:variable.unit||''}];
 if(source.kind==='history')return{columns,rows:frames.map(frame=>({x:frame.time,value:reduce(valuesAt(frame),source.statistic||'max')}))};
 if(source.kind==='probeHistory'){
  const rows=frames.map(frame=>{const mesh=meshAt(frame);if(!mesh)throw new Error('测点历史需要原始网格和真实单元中心');const point=evaluatePosition(source.position,mesh,context.parameters),sample=nearestCell(mesh,point),values=valuesAt(frame);return{x:frame.time,value:values[sample.index],cell:sample.index,distance:sample.distance};});
  return{columns:[...columns,{id:'cell',label:'最近单元'},{id:'distance',label:'采样距离'}],rows,note:'最近存储单元；不作精确插值'};
 }
 if(source.kind!=='profile')throw new Error('未注册的数据源');
 const time=source.time==='current'||source.time===undefined?context.time:source.time;
 if(source.view&&(source.time==='current'||source.time===undefined)&&context.timeUnit&&meta.timeUnit&&context.timeUnit!==meta.timeUnit)throw new Error('图表视图的时间单位不同，请指定真实保存时间');
 const frame=frames[Number.isFinite(time)?nearestFrame(frames,time):Math.min(context.state.frame||0,frames.length-1)],values=valuesAt(frame),mesh=meshAt(frame),axis=source.axis||(meta.profileAxis==='cell'?'cell':'r');
 if(values.length>50000)throw new Error('单幅剖面超过 50000 点，请使用历史统计或交付抽样曲线数据');
 const rows=values.map((value,i)=>{
  let x=i;
  if(axis==='r'){if(meta.profileAxis!=='cell'&&data.r)x=data.r[i];else if(mesh?.cellCenters){const p=mesh.cellCenters[i],a=mesh.reconstruction?.axis||'z';x=Math.hypot(...p.filter((_,k)=>k!=='xyz'.indexOf(a)));}else throw new Error('当前结果没有径向坐标');}
  else if(axis!=='cell'){if(!mesh?.cellCenters)throw new Error('当前结果没有真实单元坐标');x=mesh.cellCenters[i]['xyz'.indexOf(axis)];}
  if(!Number.isFinite(x))throw new Error('图表坐标缺失');return{x,value};
 });
 if(axis!=='cell')rows.sort((a,b)=>a.x-b.x);
 columns[0]={id:'x',label:axis==='cell'?'原始单元':axis.toUpperCase(),unit:axis==='cell'?'':meta.coordinateBounds?.unit||(axis==='r'?meta.radialUnit||'':'')};
 return{columns,rows,time:frame.time};
}

export async function resolveSource(source,context){
 let table=await rawSource(source,context);const filters=source.filter||[];
 if(source.kind==='dataset'&&source.runId){
  if(!table.columns.some(c=>c.id===source.runId))throw new Error('工况关联引用不存在的数据列');
  table={...table,columns:table.columns.some(c=>c.id==='runId')?table.columns:[...table.columns,{id:'runId',label:'参数组 ID'}],rows:table.rows.map(row=>({...row,runId:row[source.runId]}))};
 }
 if(filters.some(rule=>!table.columns.some(c=>c.id===rule.column)))throw new Error('筛选引用不存在的数据列');
 return !filters.length?table:{...table,rows:table.rows.filter(row=>filters.every(rule=>{const a=row[rule.column],b=rule.value;if(a==null)return false;if(rule.op==='eq')return a===b;if(rule.op==='ne')return a!==b;if(!Number.isFinite(a)||!Number.isFinite(b))throw new Error('范围筛选需要数值列');return({lt:()=>a<b,lte:()=>a<=b,gt:()=>a>b,gte:()=>a>=b})[rule.op]();}))};
}

export function studyTable(study,source={}){
 if(!study?.runs)throw new Error('研究数据尚未就绪');
 const columns=[{id:'record',label:'记录序号'},{id:'runId',label:'参数组 ID'},{id:'label',label:'参数组'},{id:'status',label:'状态'},{id:'statusCode',label:'状态代码'},{id:'iteration',label:'评价序号'},{id:'caseRoot',label:'计算根'},...study.parameters.map(d=>({...d,id:'parameter.'+d.id})),...study.responses.map(d=>({...d,id:'response.'+d.id}))];
 let best=new Map(),bestRun;if(source.best){const objective=study.responses.find(d=>d.id===source.best);if(!objective?.goal)throw new Error('最好值需要有实际目标方向的响应');columns.push({id:'best.'+source.best,label:'当前最好可行 · '+objective.label,unit:objective.unit});const history=bestHistory(study,source.best);best=new Map(history.map(p=>[p.run.id,p.best?.value]));bestRun=history.at(-1)?.best?.run.id;}
 const status=source.status||'completed',labels={queued:'等待',running:'执行中',completed:'已完成',failed:'失败',skipped:'跳过'};
 const rows=study.runs.flatMap((run,index)=>(status!=='all'&&run.status!==status)||(source.select==='best'&&run.id!==bestRun)?[]:[{record:index+1,...(best.get(run.id)!==undefined?{['best.'+source.best]:best.get(run.id)}:{}),runId:run.id,label:run.label||run.id,status:labels[run.status],statusCode:run.status,...(run.iteration!==undefined?{iteration:run.iteration}:{}),...(run.caseRoot?{caseRoot:run.caseRoot}:{}),...Object.fromEntries(Object.entries(run.parameters).map(([k,v])=>['parameter.'+k,v])),...Object.fromEntries(Object.entries(run.responses).map(([k,v])=>['response.'+k,v]))}]);
 return{columns,rows,note:'记录序号按保存顺序；缺失响应不补零'};
}
