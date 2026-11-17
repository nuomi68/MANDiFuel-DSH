// Extrema refer to original cells in the current frame, not color-bar limits
// or the visible cut. Ties use the first stored cell as a representative.
export function extrema(values, points){
 if(!values?.length||!points||values.length!==points.length)return [];
 let low=Infinity,high=-Infinity,imin=-1,imax=-1,nmin=0,nmax=0;
 for(let i=0;i<values.length;i++){const v=values[i];if(!Number.isFinite(v))continue;if(v<low){low=v;imin=i;nmin=1;}else if(v===low)nmin++;if(v>high){high=v;imax=i;nmax=1;}else if(v===high)nmax++;}
 if(imin<0)return [];
 const marker=(kind,index,value,count)=>({kind,index,value,count,point:points[index]});
 return low===high?[marker('constant',imin,low,nmin)]:[marker('max',imax,high,nmax),marker('min',imin,low,nmin)];
}

export function formatValue(value){
 if(value!==0&&(Math.abs(value)>=1e5||Math.abs(value)<.01))return value.toExponential(3);
 return Number(value.toPrecision(5)).toString();
}

export function markerText(marker,unit=''){
 const label={max:'最大',min:'最小',constant:'最大＝最小'}[marker.kind];
 return `${label} ${formatValue(marker.value)}${unit?' '+unit:''}${marker.count>1?'（并列 '+marker.count+' 单元）':''}`;
}
