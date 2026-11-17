import {PALETTES} from './render-style.js';

const CONTEXT=new Set(['x','y','z',...'XYZ'.split('').flatMap(a=>['min','max','size','center'].map(p=>p+a))]);
const FUNCTIONS={abs:Math.abs,min:Math.min,max:Math.max,sin:Math.sin,cos:Math.cos,tan:Math.tan,sqrt:Math.sqrt,pow:Math.pow,exp:Math.exp,log:Math.log,clamp:(v,a,b)=>Math.max(a,Math.min(b,v)),mix:(a,b,t)=>a+(b-a)*t};
const ARITY={abs:1,sin:1,cos:1,tan:1,sqrt:1,exp:1,log:1,pow:2,clamp:3,mix:3,select:3};
const PRECEDENCE={'==':10,'!=':10,'<':10,'<=':10,'>':10,'>=':10,'+':20,'-':20,'*':30,'/':30,'%':30,'**':40};
const BINARY={'+':(a,b)=>a+b,'-':(a,b)=>a-b,'*':(a,b)=>a*b,'/':(a,b)=>a/b,'%':(a,b)=>a%b,'**':(a,b)=>a**b,'<':(a,b)=>a<b,'<=':(a,b)=>a<=b,'>':(a,b)=>a>b,'>=':(a,b)=>a>=b,'==':(a,b)=>a===b,'!=':(a,b)=>a!==b};

export function compileExpression(source){
 if(typeof source!=='string'||!source.length||source.length>1200)throw new Error('显示表达式长度无效');
 const tokens=[];let pos=0;
 while(pos<source.length){
  const text=source.slice(pos),space=text.match(/^\s+/);if(space){pos+=space[0].length;continue;}
  const token=text.match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/)||text.match(/^"(?:[^"\\]|\\.)*"/)||text.match(/^[A-Za-z][A-Za-z0-9_]*/)||text.match(/^(?:\*\*|==|!=|<=|>=|[+\-*/%<>()",.])/);
  if(!token)throw new Error('显示表达式含不支持的字符');tokens.push(token[0]);pos+=token[0].length;
  if(tokens.length>200)throw new Error('显示表达式过于复杂');
 }
 let index=0;const parameters=new Set();
 const take=t=>{if(tokens[index++]!==t)throw new Error('显示表达式需要 '+t);};
 function parse(min=0,depth=0){
  if(depth>32)throw new Error('显示表达式嵌套过深');
  const token=tokens[index++];let left;
  if(token==='+'||token==='-'){const value=parse(35,depth+1);left=token==='-'?(c,p)=>-value(c,p):value;}
  else if(token==='('){left=parse(0,depth+1);take(')');}
  else if(token?.startsWith('"')){const value=JSON.parse(token);left=()=>value;}
  else if(token&&/^\d|^\.\d/.test(token)){const value=Number(token);if(!Number.isFinite(value))throw new Error('非有限表达式常量');left=()=>value;}
  else if(token==='p'){
   take('.');const name=tokens[index++];if(!/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(name)||['constructor','prototype','__proto__'].includes(name))throw new Error('参数 ID 无效');parameters.add(name);
   left=(_c,p)=>{if(!Object.hasOwn(p,name))throw new Error('未定义参数：'+name);return p[name];};
  }else if(['pi','e','True','False'].includes(token)){const value={pi:Math.PI,e:Math.E,True:true,False:false}[token];left=()=>value;}
  else if(token==='select'||Object.hasOwn(FUNCTIONS,token)){
   take('(');const args=[];if(tokens[index]!==')'){do{args.push(parse(0,depth+1));if(tokens[index]!==',')break;index++;}while(args.length<16);}take(')');
   if(!args.length||(ARITY[token]&&args.length!==ARITY[token]))throw new Error('数学函数参数数量无效：'+token);
   if(token==='select'){if(args.length!==3)throw new Error('select 需要三个参数');left=(c,p)=>args[0](c,p)?args[1](c,p):args[2](c,p);}
   else left=(c,p)=>FUNCTIONS[token](...args.map(a=>a(c,p)));
  }else if(CONTEXT.has(token))left=c=>{if(!Object.hasOwn(c,token))throw new Error('坐标上下文不可用：'+token);return c[token];};
  else throw new Error('未知显示表达式变量：'+token);
  while(Object.hasOwn(PRECEDENCE,tokens[index])&&PRECEDENCE[tokens[index]]>=min){const op=tokens[index++],right=parse(PRECEDENCE[op]+(op==='**'?0:1),depth+1),a=left;left=(c,p)=>BINARY[op](a(c,p),right(c,p));}
  return left;
 }
 const expression=parse();if(index!==tokens.length)throw new Error('显示表达式存在多余内容');expression.parameters=[...parameters];return expression;
}

export function compileProgram(program){
 if(!program)return null;
 const vertex=program.vertex?.map(compileExpression),style=Object.fromEntries(Object.entries(program.style||{}).map(([key,value])=>[key,compileExpression(value)]));
 const options=Object.fromEntries(Object.entries(program.options||{}).map(([key,value])=>[key,compileExpression(value)]));
 const fields=Object.fromEntries(Object.entries(program.fields||{}).map(([id,values])=>[id,Object.fromEntries(Object.entries(values).map(([key,value])=>[key,key==='range'?value.map(compileExpression):compileExpression(value)]))]));
 const annotations=(program.annotations||[]).map(a=>({...a,position:a.position.map(compileExpression),end:a.end?.map(compileExpression),text:a.text?compileExpression(a.text):null,color:a.color?compileExpression(a.color):null,visible:a.visible?compileExpression(a.visible):null}));
 return {label:program.label||'显示变换',vertex,style,options,fields,annotations,source:program,vertexParameters:[...new Set((vertex||[]).flatMap(f=>f.parameters))]};
}

export function meshContext(mesh){
 const context={};
 for(const [i,a] of ['X','Y','Z'].entries()){
  const lo=mesh.points.reduce((v,p)=>Math.min(v,p[i]),Infinity),hi=mesh.points.reduce((v,p)=>Math.max(v,p[i]),-Infinity);
  Object.assign(context,{['min'+a]:lo,['max'+a]:hi,['size'+a]:hi-lo,['center'+a]:(lo+hi)/2});
 }
 return context;
}

export function transformMesh(mesh,program,parameters){
 if(!program?.vertex)return mesh;
 const bounds=meshContext(mesh);
 const transform=point=>transformPoint(point,program,parameters,bounds);
 return {...mesh,points:mesh.points.map(transform),...(mesh.cellCenters?{cellCenters:mesh.cellCenters.map(transform)}:{})};
}

export function transformPoint(point,program,parameters,bounds){
 if(!program?.vertex)return point;
 const context={...bounds,x:point[0],y:point[1],z:point[2]},result=program.vertex.map(f=>f(context,parameters));
 if(!result.every(v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=1e12))throw new Error('显示变换产生无效坐标，请调整参数');
 return result;
}

export function bindOptions(program,parameters,context={}){
 const enums={cameraView:['auto','3d','xy','xz','yz'],aspectMode:['physical','fit'],displayMode:['surface','slice'],sliceAxis:['x','y','z'],scale:['fixed','frame'],extremaMode:['both','max','min']};
 const numbers={cutAngle:[0,180],slicePosition:[0,1],zoom:[.5,20],yaw:[-3600,3600],tilt:[-89,89],time:[-Infinity,Infinity],revolveAngle:[1,360]},bools=['mesh','cut','compare','extrema','revolve'];const values={};
 for(const[key,expression]of Object.entries(program?.options||{})){
  const value=expression(context,parameters);
  if(enums[key]&&!enums[key].includes(value)||bools.includes(key)&&typeof value!=='boolean'||numbers[key]&&(typeof value!=='number'||!Number.isFinite(value)||value<numbers[key][0]||value>numbers[key][1])||['field','compareField'].includes(key)&&typeof value!=='string')throw new Error('显示选项绑定无效：'+key);
  if(!enums[key]&&!numbers[key]&&!bools.includes(key)&&!['field','compareField'].includes(key))throw new Error('未知显示选项：'+key);
  values[key]=value;
 }
 return values;
}

export function bindField(program,id,parameters,context={}){
 const values={};for(const[key,expression]of Object.entries(program?.fields?.[id]||{}))values[key]=key==='range'?expression.map(f=>f(context,parameters)):expression(context,parameters);
 if(values.range&&(!values.range.every(v=>typeof v==='number'&&Number.isFinite(v))||values.range[0]>=values.range[1]))throw new Error('字段色标下限须小于上限');
 if(values.palette!==undefined&&!Object.hasOwn(PALETTES,values.palette))throw new Error('字段命名色带无效');
 if(values.reversePalette!==undefined&&typeof values.reversePalette!=='boolean')throw new Error('字段色带反转需要布尔值');
 return values;
}

export function bindStyle(style,program,parameters,context={}){
 if(!program)return style;
 const next={...style,scale:[...style.scale]};
 for(const [key,expression] of Object.entries(program.style)){
  const value=expression(context,parameters);
  if(['scaleX','scaleY','scaleZ'].includes(key)){
   if(typeof value!=='number'||!Number.isFinite(value)||value<.01||value>100)throw new Error('显示缩放绑定超出 0.01–100 范围');next.scale['XYZ'.indexOf(key.at(-1))]=value;
  }else if(key==='opacity'){
   if(typeof value!=='number'||!Number.isFinite(value)||value<.05||value>1)throw new Error('透明度绑定超出 0.05–1 范围');next[key]=value;
  }else if(key==='palette'){
   if(typeof value!=='string'||!Object.hasOwn(PALETTES,value))throw new Error('色带绑定需要可用的命名色带');next[key]=value;
  }else if(['background','wireColor'].includes(key)){
   if(typeof value!=='string'||!/^#[0-9a-fA-F]{6}$/.test(value))throw new Error('颜色绑定需要 #RRGGBB');next[key]=value;
  }else if(key==='reversePalette'){
   if(typeof value!=='boolean')throw new Error('色带反转绑定需要布尔值');next[key]=value;
  }else throw new Error('未知基础渲染绑定：'+key);
 }
 return next;
}
