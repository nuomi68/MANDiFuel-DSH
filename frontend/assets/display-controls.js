// The built-in range selector includes the inputs needed by its custom mode.
export function rangeControls(controls,program,field){
 const locked=!!program?.fields?.[field]?.range||Object.hasOwn(program?.options||{},'scale');
 const rows=controls.filter(c=>c.parameter||!(['scale','colorMin','colorMax'].includes(c.id)&&locked));
 if(!locked&&rows.some(c=>c.id==='scale'&&!c.parameter&&c.options?.some(o=>o.value==='custom'))){
  for(const [id,label]of [['colorMin','色标下限'],['colorMax','色标上限']])if(!rows.some(c=>c.id===id))rows.push({id,label,type:'number',min:-1e300,max:1e300});
 }
 return rows;
}
export function resolveRange({bound,declared,manual,scale,custom,fixed,values}){
 if(bound)return bound;
 if(!manual&&declared)return declared;
 if(scale==='custom'&&custom?.every(Number.isFinite)&&custom[1]>custom[0])return custom;
 if(scale==='fixed')return fixed;
 const lo=values.reduce((a,b)=>Math.min(a,b),Infinity),hi=values.reduce((a,b)=>Math.max(a,b),-Infinity);
 return hi>lo?[lo,hi]:[lo,lo+(Math.abs(lo)*.01||1)];
}
