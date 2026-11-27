// Read only the preparation record registered for this exact model view.
export function receiptFor(files,caseRoot){
 if(!caseRoot)return null;
 const path=caseRoot==='.'?'prepare.json':caseRoot+'/prepare.json';
 return files?.find(f=>f.path===path&&f.bytes>0&&f.bytes<=256*1024);
}
const quantityLabels={
 massFlowRate:['质量流量','kg/s'],cp:['定压比热','J/(kg·K)'],inletTemperature:['入口温度','K'],
 flowArea:['流通面积','m²'],hydraulicDiameter:['水力直径','m'],NusseltModel:['努塞尔数关联式',''],
 heatCapacityModel:['热容模型','']
};
const fixedNames={inletTemperature_K:'inletTemperature',flowArea_m2:'flowArea',hydraulicDiameter_m:'hydraulicDiameter'};
function readbackRow(entry,value,location,unit){
 if(!entry||!['number','string','boolean'].includes(typeof value)||String(value).length>500)return null;
 const field=entry.split('/').at(-1);
 const definition=fixedNames[entry]?quantityLabels[fixedNames[entry]]:entry.startsWith('boundaryField/')?quantityLabels[field]:null;
 const label=definition?.[0]||(entry.startsWith('materials/')?({material:'材料模型',k:'导热系数 k'}[field]):null)||(entry.startsWith('boundaryField/')&&field==='type'?'边界类型':field);
 const numeric=typeof value==='number'||(typeof value==='string'&&/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value));
 return {label,value:numeric&&Number.isFinite(Number(value))?Number(Number(value).toPrecision(10)):String(value),
  unit:typeof unit==='string'?unit:definition?.[1]||'',source:location+' · '+entry,raw:String(value)};
}
export function readbackSections(record){
 if(!record||typeof record!=='object')return [];
 const edited=new Set((Array.isArray(record.edits)?record.edits:[]).map(e=>e?.entry));
 const groups=new Map();
 function add(group,entry,value,location,unit){
  const row=typeof entry==='string'&&readbackRow(entry,value,location,unit);if(!row)return;
  if(!groups.has(group))groups.set(group,new Map());
  groups.get(group).set(row.source,row);
 }
 const addPath=(entry,value,location,unit)=>{
  const parts=entry.split('/').slice(0,-1);
  const namespace={boundaryField:'边界',materials:'材料区'}[parts[0]];
  const scope=namespace?[namespace,...parts.slice(1)].join(' · '):parts.join(' / ');
  add(edited.has(entry)?'本工况输入':scope||'输入回读',entry,value,location,unit);
 };
 for(const item of Array.isArray(record.readback)?record.readback:[]){
  if(typeof item?.entry==='string')addPath(item.entry,item.value,item.file||'readback',item.unit);
 }
 for(const [key,value] of Object.entries(record)){
  if(key.includes('/')&&!key.startsWith('/'))addPath(key,value,'prepare.json');
  else if((key==='fixed_inputs'||key==='readback'||key.endsWith('_readback'))&&value&&typeof value==='object'&&!Array.isArray(value)){
   for(const [entry,v] of Object.entries(value))add(key==='fixed_inputs'?'固定输入':key.replace(/_?readback$/,'')||'输入回读',entry,v,key);
  }
 }
 const ordered=[...groups].sort(([a],[b])=>Number(b==='本工况输入')-Number(a==='本工况输入'));
 return ordered.map(([title,entries])=>({title,items:[...entries.values()]}));
}
export function caseParameterSections(sections,root){
 return (sections||[]).filter(section=>!section.caseRoot||section.caseRoot===root);
}
