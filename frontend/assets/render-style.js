export const PALETTES={
 coolwarm:[[0,'#3b4cc0'],[.5,'#f0f0f0'],[1,'#b40426']],
 viridis:[[0,'#440154'],[.25,'#3b528b'],[.5,'#21918c'],[.75,'#5ec962'],[1,'#fde725']],
 inferno:[[0,'#000004'],[.25,'#57106e'],[.5,'#bc3754'],[.75,'#f98e09'],[1,'#fcffa4']],
 gray:[[0,'#171717'],[1,'#f5f5f5']],
 rainbow:[[0,'#313695'],[.25,'#74add1'],[.5,'#ffffbf'],[.75,'#f46d43'],[1,'#a50026']],
};
export function rgb(hex){return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);}
export function showScaleControls(rendering={},scale=[1,1,1]){return rendering.showScaleControls===true||scale.some(value=>value!==1);}
export function stops(palette='coolwarm'){return typeof palette==='string'?PALETTES[palette]||PALETTES.coolwarm:palette;}
export function gradient(palette,reverse=false){const rows=stops(palette);return 'linear-gradient(90deg,'+(reverse?rows.map(([v,c])=>[1-v,c]).reverse():rows).map(([v,c])=>`${c} ${v*100}%`).join(',')+')';}
export function paletteBytes(palette,reverse=false){
 const rows=stops(palette),out=new Uint8Array(256*4);
 for(let i=0;i<256;i++){
  const t=reverse?1-i/255:i/255;let j=1;while(j<rows.length-1&&rows[j][0]<t)j++;
  const [a,ca]=rows[j-1],[b,cb]=rows[j],u=(t-a)/(b-a),x=rgb(ca),y=rgb(cb);
  for(let k=0;k<3;k++)out[i*4+k]=Math.round(255*(x[k]+(y[k]-x[k])*u));out[i*4+3]=255;
 }
 return out;
}
