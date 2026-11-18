import {meshContext,transformPoint} from './render-program.js';
import {formatValue} from './extrema.js';
import {nearestCell} from './data-sources.js';

export function sceneAnnotations(mesh,program,parameters,fieldValues={},metadata=[],selectedField,view){
 if(!program?.annotations?.length)return[];
 const bounds=meshContext(mesh),context={...bounds,x:bounds.centerX,y:bounds.centerY,z:bounds.centerZ};
 const position=expressions=>{
  const p=expressions.map(f=>f(context,parameters));if(!p.every(v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e12))throw new Error('标注坐标无效');return p;
 };
 const output=[];
 for(const annotation of program.annotations){
  if(annotation.views&&!annotation.views.includes(view))continue;
  if(annotation.visible){const visible=annotation.visible(context,parameters);if(typeof visible!=='boolean')throw new Error('标注开关需要布尔值');if(!visible)continue;}
  const sourcePoint=position(annotation.position),point=transformPoint(sourcePoint,program,parameters,bounds);
  const color=annotation.color?annotation.color(context,parameters):'#247d70';if(typeof color!=='string'||!/^#[0-9a-fA-F]{6}$/.test(color))throw new Error('标注颜色无效');
  const content=annotation.text?annotation.text(context,parameters):annotation.label||'标注';let text=typeof content==='number'?formatValue(content):String(content);
  const marker={kind:annotation.type==='probe'?'probe':'annotation',id:annotation.id,point,sourcePoint,color,text,type:annotation.type};
  if(annotation.type==='circle'){
   const radius=annotation.radius(context,parameters);if(!Number.isFinite(radius)||radius<=0||radius>1e12)throw new Error('圆形界面导引需要正半径');
   const axis='xyz'.indexOf(annotation.axis||'y'),plane=[0,1,2].filter(i=>i!==axis);
   marker.path=Array.from({length:65},(_,i)=>{const p=[...sourcePoint],angle=i/64*Math.PI*2;p[plane[0]]+=radius*Math.cos(angle);p[plane[1]]+=radius*Math.sin(angle);return transformPoint(p,program,parameters,bounds);});
   marker.point=marker.path[8];marker.radius=radius;
  }
  if(annotation.type==='line'||annotation.type==='arrow')marker.end=transformPoint(position(annotation.end),program,parameters,bounds);
  if(annotation.type==='probe'){
   const field=annotation.field&&annotation.field!=='selected'?annotation.field:selectedField,values=fieldValues[field],centres=mesh.cellCenters;
   if(!centres?.length||!values||centres.length!==values.length)throw new Error('点值标注需要实际字段及原始单元中心，请重新导出已有结果');
   const sample=nearestCell(mesh,sourcePoint),index=sample.index;
   const meta=metadata.find(f=>f.id===field);if(index<0||!meta||!Number.isFinite(values[index]))throw new Error('点值标注字段不可用');
   Object.assign(marker,{index,sourceCell:mesh.cellIds?.[index]??index,value:values[index],field,unit:meta.unit,distance:sample.distance,samplePoint:sample.samplePoint});
   text=`${annotation.label||'测点'} · ${meta.symbol||meta.label||field} ${formatValue(marker.value)} ${meta.unit||''}（最近单元）`;
  }
  marker.text=text;output.push(marker);
 }
 return output;
}
