import {sliceMesh} from './mesh-slice.js';
import {extrema,markerText} from './extrema.js';
import {paletteBytes,rgb} from './render-style.js';
import {transformMesh} from './render-program.js';
import {sceneAnnotations} from './scene-annotations.js';
const VERTEX = `
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute float aValue;
uniform vec4 uCamera;
uniform vec2 uRange;
uniform vec2 uPan;
uniform vec3 uStretch;
uniform float uWire;
varying float vValue;
varying float vLight;
varying vec3 vPosition;
vec3 rotate(vec3 v) {
 float cy=cos(uCamera.x), sy=sin(uCamera.x), ct=cos(uCamera.y), st=sin(uCamera.y);
 vec3 q=vec3(v.x*cy-v.y*sy,v.x*sy+v.y*cy,v.z);
 return vec3(q.x,q.y*ct+q.z*st,q.z*ct-q.y*st);
}
void main(){
 vPosition=aPosition;
 vec3 q=rotate(aPosition*uStretch);
 gl_Position=vec4(q.x*uCamera.z/uCamera.w+uPan.x,q.z*uCamera.z+uPan.y,-q.y*0.12,1.0);
 vValue=clamp((aValue-uRange.x)/(uRange.y-uRange.x),0.0,1.0);
 vec3 n=normalize(rotate(aNormal/uStretch));
 vLight=0.72+0.28*abs(dot(n,normalize(vec3(-0.35,0.65,0.7))));
}`;
const FRAGMENT = `
precision mediump float;
varying float vValue;
varying float vLight;
uniform float uWire;
uniform float uClip;
uniform float uGeometryOnly;
uniform float uClipAngle;
uniform sampler2D uPalette;
uniform vec3 uWireColor;
uniform float uOpacity;
varying vec3 vPosition;
void main(){
 if(uClip>0.5 && dot(vPosition.xy,vec2(cos(uClipAngle),sin(uClipAngle)))>0.0) discard;
 vec3 c=texture2D(uPalette,vec2((vValue*255.0+0.5)/256.0,0.5)).rgb;
 gl_FragColor = uWire > 0.5 ? vec4(uWireColor,0.35) : vec4((uGeometryOnly>0.5 ? vec3(0.56,0.69,0.86) : c)*vLight,uOpacity);
}`;

export class ModelViewer {
 constructor(canvas, {onCameraChange=()=>{}, onError=()=>{}}={}) {
  this.canvas=canvas;this.onCameraChange=onCameraChange;this.onError=onError;
  this.overlay=document.createElement('canvas');this.overlay.className='extrema-overlay';this.overlay.dataset.for=canvas.id;this.overlay.hidden=true;this.overlay.setAttribute('role','img');canvas.insertAdjacentElement('afterend',this.overlay);this.annotations=null;
  this.camera={yaw:1.10,tilt:0.34,zoom:1,panX:0,panY:0};this.viewMode='3d';this.aspectMode='physical';this.displayMode='surface';this.sliceAxis='z';this.slicePosition=.5;this.sliceCache=null;this.cut=true;this.mesh=false;this.cutAngle=90;this.axialScale=0.16;this.geometryKey='';this.faces=[];this.model=null;this.range=[0,1];this.pending=false;this.drag=null;
  const gl=canvas.getContext('webgl',{antialias:true,alpha:true,preserveDrawingBuffer:true});
  if(!gl) throw new Error('当前浏览器无法启用 WebGL，请开启硬件加速后刷新。');
  this.gl=gl;this.program=this.makeProgram(VERTEX,FRAGMENT);gl.useProgram(this.program);
  this.paletteTexture=gl.createTexture();this.style={scale:[1,1,1],palette:'coolwarm',reversePalette:false,opacity:1,wireColor:'#3d6eb3'};
  this.locations={position:gl.getAttribLocation(this.program,'aPosition'),normal:gl.getAttribLocation(this.program,'aNormal'),value:gl.getAttribLocation(this.program,'aValue'),stretch:gl.getUniformLocation(this.program,'uStretch'),pan:gl.getUniformLocation(this.program,'uPan'),camera:gl.getUniformLocation(this.program,'uCamera'),range:gl.getUniformLocation(this.program,'uRange'),wire:gl.getUniformLocation(this.program,'uWire'),geometryOnly:gl.getUniformLocation(this.program,'uGeometryOnly'),clip:gl.getUniformLocation(this.program,'uClip'),clipAngle:gl.getUniformLocation(this.program,'uClipAngle')};
  for(const name of ['Palette','WireColor','Opacity'])this.locations[name]=gl.getUniformLocation(this.program,'u'+name);
  this.buffers={positions:gl.createBuffer(),normals:gl.createBuffer(),values:gl.createBuffer(),edges:gl.createBuffer()};
  this.resizeObserver=new ResizeObserver(()=>this.draw());this.resizeObserver.observe(canvas);
  canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;this.drag={x:e.clientX,y:e.clientY,yaw:this.camera.yaw,tilt:this.camera.tilt,panX:this.camera.panX||0,panY:this.camera.panY||0};canvas.setPointerCapture(e.pointerId);canvas.classList.add('dragging');});
  canvas.addEventListener('pointermove',e=>{if(!this.drag)return;if(this.viewMode!=='3d'){const box=canvas.getBoundingClientRect();this.camera.panX=this.drag.panX+2*(e.clientX-this.drag.x)/box.width;this.camera.panY=this.drag.panY-2*(e.clientY-this.drag.y)/box.height;this.draw();this.onCameraChange(this.camera);return;}this.camera.yaw=this.drag.yaw+(e.clientX-this.drag.x)*0.009;this.camera.tilt=Math.max(-1.25,Math.min(1.25,this.drag.tilt+(e.clientY-this.drag.y)*0.007));this.draw();this.onCameraChange(this.camera);});
  const end=()=>{if(!this.drag)return;this.drag=null;canvas.classList.remove('dragging');this.onCameraChange(this.camera);};
  canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
  canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom(Math.exp(-e.deltaY*0.001));},{passive:false});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.onError('模型显示已暂停，请刷新页面重新加载。');});
 }
 makeProgram(vs,fs){const gl=this.gl;const compile=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;};const p=gl.createProgram();gl.attachShader(p,compile(gl.VERTEX_SHADER,vs));gl.attachShader(p,compile(gl.FRAGMENT_SHADER,fs));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));return p;}
 setModel(task,sampler,range,sourceKey=''){this.geometryOnly=false;this.native=false;this.model=task;this.sampler=sampler;this.range=range;const key=JSON.stringify([sourceKey,task.id,task.shape,task.radius,task.innerRadius,task.length,task.cells,task.radialBands,this.cut,this.cutAngle,this.axialScale]);if(key!==this.geometryKey){this.geometryKey=key;this.buildGeometry();}this.updateValues();this.draw();}
 setNativeModel(task,mesh,values,range,key){
  this.sourceMesh=mesh;
  if(this.displayProgram?.vertex){
   const programKey=key+':'+this.displayProgramKey;
   if(this.displayMeshCache?.key!==programKey||this.displayMeshCache.source!==mesh)this.displayMeshCache={key:programKey,source:mesh,mesh:transformMesh(mesh,this.displayProgram,this.displayParameters)};
   mesh=this.displayMeshCache.mesh;key=programKey;
  }
  this.markerPoints=mesh.cellCenters;this.reconstruction=mesh.reconstruction;
  const original=mesh;if(this.displayMode==='slice'){const sliceKey=key+':'+this.sliceAxis+':'+this.slicePosition;if(this.sliceCache?.key!==sliceKey||this.sliceCache.source!==original)this.sliceCache={key:sliceKey,source:original,mesh:sliceMesh(original,this.sliceAxis,this.slicePosition)};mesh=this.sliceCache.mesh;key=sliceKey;}else key+=':surface';
  this.geometryOnly=false;this.native=true;this.model=task;this.range=range;this.nativeValues=values;
  if(this.geometryKey!==key){this.geometryKey=key;const points=mesh.points;const boundPoints=original.points;const lo=[0,1,2].map(i=>boundPoints.reduce((a,p)=>Math.min(a,p[i]),Infinity)),hi=[0,1,2].map(i=>boundPoints.reduce((a,p)=>Math.max(a,p[i]),-Infinity));const center=lo.map((x,i)=>(x+hi[i])/2),scale=Math.max(...hi.map((x,i)=>x-lo[i]))/2||1;
   this.nativeCenter=center;this.nativeScale=scale;this.nativeExtent=scale*2;this.nativeSpan=[0,1,2].map(i=>points.reduce((a,p)=>Math.max(a,p[i]),-Infinity)-points.reduce((a,p)=>Math.min(a,p[i]),Infinity));this.canvas.dataset.modelBounds=JSON.stringify({min:lo,max:hi});
   const positions=[],normals=[],edges=[],cells=[];
   for(let k=0;k<mesh.triangles.length;k+=3){const ps=mesh.triangles.slice(k,k+3).map(i=>points[i].map((x,j)=>(x-center[j])/scale));const normal=polygonNormal(ps);for(const p of ps){positions.push(...p);normals.push(...normal);cells.push(mesh.cells[k/3]);}for(let i=0;i<3;i++)edges.push(...ps[i],...ps[(i+1)%3]);}
   this.vertexCount=cells.length;this.edgeCount=edges.length/3;this.vertexCells=cells;const gl=this.gl;for(const[name,array]of[['positions',positions],['normals',normals],['edges',edges]]){gl.bindBuffer(gl.ARRAY_BUFFER,this.buffers[name]);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(array),gl.STATIC_DRAW);}
  }
  this.updateValues();this.draw();
 }
 setMeshPreview(task,mesh,key){this.setNativeModel(task,mesh,new Array(task.cells).fill(0),[0,1],key);this.geometryOnly=true;this.draw();}
 clear(){this.model=null;this.geometryKey='';this.annotations=null;this.sceneMarkers=[];this.overlay.hidden=true;this.draw();}
 setAnnotations(enabled,values,unit,radial,mode='both'){
  const points=this.native?this.markerPoints:radial?.map(r=>[r,0,0]);
  this.annotations=enabled&&!this.geometryOnly?{markers:extrema(values,points).filter(m=>mode==='both'||m.kind===mode||m.kind==='constant'),unit}:null;this.draw();
 }
 setSceneAnnotations(program,parameters,values,metadata,selected){this.sceneMarkers=program?.annotations?.length?sceneAnnotations(this.sourceMesh,program,parameters,values,metadata,selected):[];this.draw();}
 setProgramCamera(options){
  const camera=Object.fromEntries(['zoom','yaw','tilt'].filter(k=>options[k]!==undefined).map(k=>[k,options[k]])),key=JSON.stringify([camera,options.cameraDirectiveRevision||0]);
  if(key!==this.programCameraKey){this.programCameraKey=key;for(const[k,v]of Object.entries(camera))this.camera[k]=k==='zoom'?v:v*Math.PI/180;this.draw();}
 }
 setStyle(style){
  this.style={...this.style,...style};const key=JSON.stringify([this.style.palette,this.style.reversePalette]);
  if(key!==this.paletteKey){this.paletteKey=key;const gl=this.gl;gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.paletteTexture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,256,1,0,gl.RGBA,gl.UNSIGNED_BYTE,paletteBytes(this.style.palette,this.style.reversePalette));gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);}
  this.canvas.dataset.rendering=JSON.stringify(this.style);this.draw();
 }
 setDisplayProgram(program,parameters={}){
  this.displayProgram=program;this.displayParameters={...parameters};this.displayProgramKey=JSON.stringify([program?.source?.vertex,(program?.vertexParameters||[]).map(id=>[id,parameters[id]])]);
  this.canvas.dataset.displayProgram=JSON.stringify(program?{label:program.label,parameters}:null);
 }
 setOptions({cut=this.cut,mesh=this.mesh,cutAngle=this.cutAngle,axialScale=this.axialScale}={}){this.cut=cut;this.mesh=mesh;this.cutAngle=cutAngle;this.axialScale=axialScale;if(this.model)this.setModel(this.model,this.sampler,this.range);}
 setView(mode='3d',force=false){if(mode===this.viewMode&&!force)return;this.viewMode=mode;const angles={xy:[0,-Math.PI/2],xz:[0,0],yz:[-Math.PI/2,0],'3d':[1.1,.34]};const [yaw,tilt]=angles[mode]||angles['3d'];Object.assign(this.camera,{yaw,tilt,panX:0,panY:0});this.draw();}
 reset(){this.camera.zoom=1;this.setView(this.viewMode,true);this.onCameraChange(this.camera);}
 zoom(factor){this.camera.zoom=Math.max(.5,Math.min(20,this.camera.zoom*factor));this.draw();this.onCameraChange(this.camera);}
 buildGeometry(){const task=this.model;this.faces=[];const segments=64,lat=32;const half=this.cut?this.cutAngle*Math.PI/360:0,p0=half,p1=Math.PI*2-half;const add=(points,r)=>this.faces.push({points,r});
  if(task.shape==='rod'){
   const zmax=(task.length||task.radius*4)/task.radius*this.axialScale/2;
   const point=(r,p,z)=>[r*Math.cos(p),r*Math.sin(p),z];
   for(const [a,b,n] of (task.radialBands||[[task.innerRadius||0,task.radius,Math.min(task.cells,160)]])){const rin=a/task.radius,rout=b/task.radius;
    for(let j=0;j<segments;j++){const p=p0+(p1-p0)*j/segments,q=p0+(p1-p0)*(j+1)/segments;add([point(rout,p,-zmax),point(rout,q,-zmax),point(rout,q,zmax),point(rout,p,zmax)],rout*task.radius);if(rin>0)add([point(rin,q,-zmax),point(rin,p,-zmax),point(rin,p,zmax),point(rin,q,zmax)],rin*task.radius);}
    for(let k=0;k<n;k++){const r=rin+(rout-rin)*k/n,rr=rin+(rout-rin)*(k+1)/n,mid=(r+rr)/2*task.radius;
     for(const z of [-zmax,zmax])for(let j=0;j<segments;j++){const p=p0+(p1-p0)*j/segments,q=p0+(p1-p0)*(j+1)/segments;add([point(r,p,z),point(rr,p,z),point(rr,q,z),point(r,q,z)],mid);}
     if(this.cut)for(const p of [p0,p1])add([point(r,p,-zmax),point(rr,p,-zmax),point(rr,p,zmax),point(r,p,zmax)],mid);
    }
   }
  }else{
   const sphere=(r,p,t)=>[r*Math.sin(t)*Math.cos(p),r*Math.sin(t)*Math.sin(p),r*Math.cos(t)];
   const lo=task.innerRadius/task.radius;
   for(const radius of lo>0?[lo,1]:[1])for(let k=0;k<lat;k++){const t=Math.PI*k/lat,tt=Math.PI*(k+1)/lat;for(let j=0;j<segments;j++){const p=p0+(p1-p0)*j/segments,q=p0+(p1-p0)*(j+1)/segments;add([sphere(radius,p,t),sphere(radius,q,t),sphere(radius,q,tt),sphere(radius,p,tt)],radius*task.radius);}}
   if(this.cut){const layers=task.cells;for(const p of [p0,p1])for(let k=0;k<layers;k++){const r=lo+(1-lo)*k/layers,rr=lo+(1-lo)*(k+1)/layers;for(let j=0;j<lat;j++){const t=Math.PI*j/lat,tt=Math.PI*(j+1)/lat;add([sphere(r,p,t),sphere(rr,p,t),sphere(rr,p,tt),sphere(r,p,tt)],(r+rr)/2*task.radius);}}}
  }
  const positions=[],normals=[],radii=[],edges=[];
  for(const face of this.faces){const ps=face.points;const normal=polygonNormal(ps);for(const i of [0,1,2,0,2,3]){positions.push(...ps[i]);normals.push(...normal);radii.push(face.r);}for(let i=0;i<4;i++)edges.push(...ps[i],...ps[(i+1)%4]);}
  this.vertexCount=radii.length;this.edgeCount=edges.length/3;this.radii=radii;
  const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,this.buffers.positions);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(positions),gl.STATIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffers.normals);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(normals),gl.STATIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffers.edges);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(edges),gl.STATIC_DRAW);
 }
 updateValues(){
  const gl=this.gl,source=this.native?this.vertexCells.map(i=>this.nativeValues[i]):this.radii.map(this.sampler),[lo,hi]=this.range,span=hi-lo||1;
  if(!source.length||!source.every(Number.isFinite))throw new Error('显示几何未映射到有效物理场，请检查当前变量与重建视图');
  const dataMin=source.reduce((a,v)=>Math.min(a,v),Infinity),dataMax=source.reduce((a,v)=>Math.max(a,v),-Infinity);
  this.canvas.dataset.fieldMapping=JSON.stringify({vertices:source.length,sampledRange:[dataMin,dataMax],colorRange:[lo,hi],geometry:this.native?'mesh':this.model.shape,cut:this.cut});
  const values=new Float32Array(source.map(v=>Math.max(0,Math.min(1,(v-lo)/span))));gl.bindBuffer(gl.ARRAY_BUFFER,this.buffers.values);gl.bufferData(gl.ARRAY_BUFFER,values,gl.DYNAMIC_DRAW);
 }
 draw(){if(this.pending)return;this.pending=true;requestAnimationFrame(()=>{this.pending=false;this.render();});}
 render(){const gl=this.gl,canvas=this.canvas,box=canvas.getBoundingClientRect(),ratio=Math.min(2,window.devicePixelRatio||1),w=Math.max(1,Math.round(box.width*ratio)),h=Math.max(1,Math.round(box.height*ratio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);if(!this.model)return;
  gl.useProgram(this.program);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);
  const extent=this.model.shape==='rod'?Math.max(1.65,(this.model.length||this.model.radius*4)/this.model.radius*this.axialScale/2+0.5):1.45;
  const aspect=w/h,axes={xy:[0,1],xz:[0,2],yz:[1,2]}[this.viewMode];let stretch=[...this.style.scale],scale=Math.min(1/extent,aspect/1.55)*this.camera.zoom/Math.max(...stretch);
  if(this.native&&axes&&this.nativeSpan){const [a,b]=axes,ea=Math.max(this.nativeSpan[a]/this.nativeExtent,1e-12),eb=Math.max(this.nativeSpan[b]/this.nativeExtent,1e-12);if(this.aspectMode==='fit'){scale=this.camera.zoom/(1.45*Math.max(stretch[a],stretch[b]));stretch[a]*=aspect/ea;stretch[b]*=1/eb;}else scale=Math.min(aspect/(ea*stretch[a]*1.45),1/(eb*stretch[b]*1.45))*this.camera.zoom;}
  this.projection={scale,aspect,stretch};
  gl.uniform3f(this.locations.stretch,...stretch);
  gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.paletteTexture);gl.uniform1i(this.locations.Palette,0);gl.uniform3f(this.locations.WireColor,...rgb(this.style.wireColor));gl.uniform1f(this.locations.Opacity,this.style.opacity);gl.enable(gl.BLEND);gl.blendFuncSeparate(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA,gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
  gl.uniform2f(this.locations.pan,this.camera.panX||0,this.camera.panY||0);gl.uniform4f(this.locations.camera,this.camera.yaw,this.camera.tilt,scale,aspect);gl.uniform2f(this.locations.range,0,1);gl.uniform1f(this.locations.wire,0);gl.uniform1f(this.locations.geometryOnly,this.geometryOnly?1:0);gl.uniform1f(this.locations.clip,this.native&&this.cut&&this.displayMode!=='slice'?1:0);gl.uniform1f(this.locations.clipAngle,this.cutAngle*Math.PI/180);
  const attribute=(buffer,loc,n)=>{gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,n,gl.FLOAT,false,0,0);};attribute(this.buffers.positions,this.locations.position,3);attribute(this.buffers.normals,this.locations.normal,3);attribute(this.buffers.values,this.locations.value,1);gl.drawArrays(gl.TRIANGLES,0,this.vertexCount);gl.disable(gl.POLYGON_OFFSET_FILL);
  if(this.mesh){attribute(this.buffers.edges,this.locations.position,3);gl.disableVertexAttribArray(this.locations.normal);gl.vertexAttrib3f(this.locations.normal,0,1,0);gl.disableVertexAttribArray(this.locations.value);gl.vertexAttrib1f(this.locations.value,0);gl.uniform1f(this.locations.wire,1);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.depthMask(false);gl.drawArrays(gl.LINES,0,this.edgeCount);gl.depthMask(true);gl.disable(gl.BLEND);}
  this.drawAnnotations();
 }
 drawAnnotations(){
  const overlay=this.overlay,markers=[...(this.annotations?.markers||[]),...(this.sceneMarkers||[])];overlay.hidden=!this.model||!markers.length||this.canvas.hidden;if(overlay.hidden)return;
  const box=this.canvas.getBoundingClientRect(),w=box.width,h=box.height,ratio=this.canvas.width/w;
  Object.assign(overlay.style,{left:this.canvas.offsetLeft+'px',top:this.canvas.offsetTop+'px',width:w+'px',height:h+'px'});overlay.width=this.canvas.width;overlay.height=this.canvas.height;
  const ctx=overlay.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);ctx.font='11px "Workbench CJK",system-ui';ctx.textBaseline='middle';
  const descriptions=[],boxes=[];
  const project=point=>{
   let p=point;if(this.native)p=p.map((v,i)=>(v-this.nativeCenter[i])/this.nativeScale);else{const r=p[0]/this.model.radius,phi=this.cut?-this.cutAngle*Math.PI/360:0;p=[r*Math.cos(phi),r*Math.sin(phi),0];}
   const {scale,aspect,stretch}=this.projection,{yaw,tilt,panX=0,panY=0}=this.camera;p=p.map((v,i)=>v*stretch[i]);const qx=p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),qy=p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw),qz=p[2]*Math.cos(tilt)-qy*Math.sin(tilt);
   return{x:(qx*scale/aspect+panX+1)*w/2,y:(1-qz*scale-panY)*h/2};
  };
  for(const marker of markers){
   let {x,y}=project(marker.point),label=marker.text??markerText(marker,this.annotations?.unit||'');const color=marker.color||(marker.kind==='min'?'#3b4cc0':marker.kind==='max'?'#b40426':'#476a9c');
   if(marker.end){const end=project(marker.end);ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(end.x,end.y);ctx.stroke();if(marker.type==='arrow'){const angle=Math.atan2(end.y-y,end.x-x);ctx.beginPath();ctx.moveTo(end.x,end.y);ctx.lineTo(end.x-9*Math.cos(angle-.4),end.y-9*Math.sin(angle-.4));ctx.moveTo(end.x,end.y);ctx.lineTo(end.x-9*Math.cos(angle+.4),end.y-9*Math.sin(angle+.4));ctx.stroke();}x=(x+end.x)/2;y=(y+end.y)/2;}
   descriptions.push(label+(marker.index!==undefined?'，原始单元 '+marker.index:'')+(marker.sourcePoint?'，坐标 '+marker.sourcePoint.join(', '):''));
   if(x<0||x>w||y<0||y>h){if(!marker.id)continue;label+='（视野外）';x=Math.max(8,Math.min(w-8,x));y=Math.max(70,Math.min(h-80,y));}
   const width=Math.min(w-16,ctx.measureText(label).width+16),height=26,left=Math.max(8,Math.min(w-width-8,x+12)),safeBottom=Math.max(70,h-90-height);let top=Math.max(70,Math.min(safeBottom,y+(marker.kind==='min'?14:-38)));
   while(boxes.some(b=>left<b.x+b.w&&left+width>b.x&&top<b.y+b.h&&top+height>b.y)&&top+34<=safeBottom)top+=34;
   boxes.push({x:left,y:top,w:width,h:height});ctx.strokeStyle=color;ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(Math.max(left,Math.min(left+width,x)),top+height/2);ctx.stroke();ctx.setLineDash([]);
   ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();ctx.fillStyle='#fffffff0';ctx.fillRect(left,top,width,height);ctx.strokeStyle=color;ctx.lineWidth=.7;ctx.strokeRect(left,top,width,height);ctx.fillStyle=color;ctx.save();ctx.beginPath();ctx.rect(left+3,top,width-6,height);ctx.clip();ctx.fillText(label,left+8,top+height/2);ctx.restore();
  }
  overlay.dataset.markers=JSON.stringify(markers);overlay.setAttribute('aria-label',(this.annotations?.markers?.length?'当前帧全域极值。':'')+'当前保存帧标注。'+descriptions.join('；'));
  ctx.fillStyle='#617897';ctx.font='10px "Workbench CJK",system-ui';const note=this.annotations?.markers?.length?'当前帧全域 · 单元中心透视标记':markers.some(m=>m.kind==='probe')?'点值取最近存储单元':'坐标标注';ctx.fillText(note,10,h-10);
 }

 projectAxis(v){const {yaw,tilt}=this.camera;const x=v[0]*Math.cos(yaw)-v[1]*Math.sin(yaw),y=v[0]*Math.sin(yaw)+v[1]*Math.cos(yaw);return[x,v[2]*Math.cos(tilt)-y*Math.sin(tilt)];}
 screenshot(){this.render();if(this.overlay.hidden)return this.canvas;const out=document.createElement('canvas');out.width=this.canvas.width;out.height=this.canvas.height;const ctx=out.getContext('2d');ctx.drawImage(this.canvas,0,0);ctx.drawImage(this.overlay,0,0);return out;}
}
function polygonNormal(ps){for(let i=1;i<ps.length-1;i++){const a=ps[i].map((x,j)=>x-ps[0][j]),b=ps[i+1].map((x,j)=>x-ps[0][j]),n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],m=Math.hypot(...n);if(m>1e-10)return n.map(x=>x/m);}return[0,1,0];}
