// Navigation transforms coordinates only; stored observations are never edited.
export function axisValue(axis,fraction){
 const f=axis.reverse?1-fraction:fraction;
 return axis.scale==='log'?Math.exp(Math.log(axis.min)+(Math.log(axis.max)-Math.log(axis.min))*f):axis.min+(axis.max-axis.min)*f;
}
export function zoomViewport(domain,fractions){
 return Object.fromEntries(['x','y'].filter(key=>!domain[key].category).map(key=>{const pair=fractions[key].map(f=>axisValue(domain[key],f)).sort((a,b)=>a-b);if(!pair.every(Number.isFinite)||pair[0]>=pair[1])throw new Error('缩放范围无效');return[key,pair];}));
}
export function centeredZoom(domain,factor){return zoomViewport(domain,{x:[.5-.5*factor,.5+.5*factor],y:[.5-.5*factor,.5+.5*factor]});}
