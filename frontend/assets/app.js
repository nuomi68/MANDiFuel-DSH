import {ModelViewer} from './model-viewer.js';
import {gradient,stops,showScaleControls} from './render-style.js';
import {compileProgram,bindStyle,bindOptions,bindField,meshContext} from './render-program.js';
import {renderParameterPanel} from './parameter-panel.js';
import {NativeHarness,statusLabel} from './native-harness.js';
import {ExecutionProcess} from './execution-process.js';
import {DeliveryBrowser} from './delivery-browser.js';
import {StudyPanel,runLabel,displayNumber} from './study-panel.js';
import {nearestFrame} from './study-math.js';
import {rotationProfile,revolveMesh,meridionalMesh} from './revolve-mesh.js';
import {AdaptiveUI} from './adaptive-ui.js';
import {groupSettingsControls} from './ui-placement.js';
import {fieldSummary} from './field-summary.js';
import {FrontendStateObserver} from './frontend-state.js';
import {rangeControls,resolveRange} from './display-controls.js';
import {PresentationActivity} from './presentation-activity.js';
const BASE='/workbench';
let settingsPlacementKey=null,frontendObserver=null,presentationActivity=null;

const $=id=>document.getElementById(id);
const els=Object.fromEntries([...document.querySelectorAll('[id]')].map(el=>[el.id,el]));
const storageKey='mandifuel-workbench-v4';
const state={task:null,view:null,field:null,parameters:{},frame:0,cut:false,mesh:false,cutAngle:90,axialScale:0.16,scale:'fixed',scaleX:1,scaleY:1,scaleZ:1,palette:'coolwarm',reversePalette:false,opacity:1,background:'#fbfbfc',wireColor:'#5b6472',colorMin:0,colorMax:1,extrema:false,cameraView:'auto',displayMode:'surface',sliceAxis:'z',slicePosition:.5,compare:false,compareField:null,aspectMode:'physical',rotation:null,run:null,panel:'overview'};
try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved&&typeof saved==='object'){for(const key of ['task','view','field','frame','cut','mesh','cutAngle','axialScale','scale','scaleX','scaleY','scaleZ','palette','reversePalette','opacity','background','wireColor','colorMin','colorMax','extrema','cameraView','displayMode','sliceAxis','slicePosition','compare','compareField','aspectMode','rotation','run','panel'])if(key in saved)state[key]=saved[key];}}catch{}
state.cut=state.cut===true;state.mesh=state.mesh===true;state.cutAngle=clamp(Number.isFinite(Number(state.cutAngle))?Number(state.cutAngle):90,0,180);state.axialScale=clamp(Number(state.axialScale)||0.16,0.08,1);state.scale=['frame','custom'].includes(state.scale)?state.scale:'fixed';
let dsh=null,execution=null,delivery=null,loadedVersion=null,model=null,presentationKey=null,studyPanel=null,studyData=null,studyKey=null,pendingStudyTime=null,adaptive=null;
const studyCache=new Map(),studySelections=new Map();
const customRanges=new Map();
const overrides=new Map();let renderingKey=null,parameterKey=null,programSource=null,displayProgram=null,parameterSyncTimer=null;const programBoundsCache=new WeakMap();let viewDirectiveKey=null,selectedViewDirectiveKey=null,pendingCamera={},cameraDirectiveRevision=0,cameraPresetRevision=0,viewerSyncTimer=null,pendingViewerObservation=null;
const renderIds=['scaleX','scaleY','scaleZ','palette','reversePalette','opacity','background','wireColor','colorMin','colorMax','scale'];
function renderingBindings(){const r=task?.presentation?.rendering||{};return{scaleX:r.scale?.[0],scaleY:r.scale?.[1],scaleZ:r.scale?.[2],palette:r.palette,reversePalette:r.reversePalette,opacity:r.opacity,background:r.background,wireColor:r.wireColor};}
function renderStyle(id=state.field){
 const f=task?.presentation?.rendering?.fields?.[id]||{},manual=k=>overrides.has(`${task.id}:${state.view}:${k}`),program=currentProgram(),context=program?programContext():{};
 const base=bindStyle({scale:[state.scaleX,state.scaleY,state.scaleZ],palette:manual('palette')?state.palette:f.palette??state.palette,reversePalette:manual('reversePalette')?state.reversePalette:f.reversePalette??state.reversePalette,opacity:state.opacity,wireColor:state.wireColor,background:state.background},program,state.parameters,context);
 const field=bindField(program,id,state.parameters,context);return{...base,palette:field.palette??base.palette,reversePalette:field.reversePalette??base.reversePalette};
}

function currentProgram(){const source=task?.presentation?.rendering?.program||null,key=JSON.stringify(source);if(key!==programSource){displayProgram=compileProgram(source);programSource=key;}return displayProgram;}
function programContext(){const mesh=fields?.kind==='mesh'?fields.mesh:fields?.meshes?.[frame()?.mesh];if(!mesh)return{};if(!programBoundsCache.has(mesh))programBoundsCache.set(mesh,meshContext(mesh));const c=programBoundsCache.get(mesh);return{...c,x:c.centerX,y:c.centerY,z:c.centerZ};}
function applyProgramOptions(){
 const presentation=task.presentation||{},directive=presentation.viewState||{},directiveKey=JSON.stringify([task.id,presentation.viewStateRevision||0,directive]);
 const apply=options=>{
  for(const key of ['field','compareField'])if(fields.kind!=='mesh'&&options[key]!==undefined&&!model.fields.some(f=>f.id===options[key]))throw new Error('显示选项引用了不存在的字段：'+options[key]);
  if(options.displayMode==='slice'&&(model.shape!=='mesh'||model.supportsSlice===false))throw new Error('当前视图没有内部切片拓扑，请使用原始网格视图');
  if((options.revolve!==undefined||options.revolveAngle!==undefined)&&!rotationAvailable())throw new Error('当前网格没有可旋转的二维轴对称截面');
  for(const[key,value]of Object.entries(options)){if(fields.kind==='mesh'&&['field','compareField','time'].includes(key))continue;if(key==='revolve')state.rotation.enabled=value;else if(key==='revolveAngle')state.rotation.angle=value;else if(!['time','zoom','yaw','tilt','view'].includes(key))state[key]=value;}
  if(fields.kind!=='mesh'&&options.time!==undefined){if(!fields.frames?.length)throw new Error('当前没有保存的时间帧');state.frame=nearestFrame(fields.frames,options.time);}
 };
 if(directiveKey!==viewDirectiveKey){viewDirectiveKey=directiveKey;if(directive.cameraView!==undefined)cameraPresetRevision++;apply(directive);for(const[k,v]of Object.entries(directive))if(!['time','zoom','yaw','tilt','view','field','compareField'].includes(k))overrides.set(`${task.id}:${state.view}:${k}`,v);const camera=Object.fromEntries(['zoom','yaw','tilt'].filter(k=>directive[k]!==undefined).map(k=>[k,directive[k]]));if(Object.keys(camera).length){pendingCamera=camera;cameraDirectiveRevision++;}}
 const options=bindOptions(currentProgram(),state.parameters,programContext());state.extremaMode=options.extremaMode||state.extremaMode||'both';apply(options);
 if(fields.kind!=='mesh'){els['field-select'].value=state.field;els['field-select'].disabled=Object.hasOwn(options,'field');}
 els['compare-field-select'].disabled=Object.hasOwn(options,'compareField');els['time-range'].disabled=Object.hasOwn(options,'time');els['play-button'].disabled=Object.hasOwn(options,'time');
 return {...pendingCamera,...options,cameraDirectiveRevision,cameraPresetRevision};
}
function syncViewerState(error=''){
 if(!task||!fields||!model||!dsh?.token||loadedVersion!==modelLoadKey())return;
 const observation={revision:task.presentation?.viewStateRevision||0,view:state.view,cameraView:state.cameraView,displayMode:state.displayMode,sliceAxis:state.sliceAxis,slicePosition:state.slicePosition,compare:state.compare,revolve:rotationActive(),revolveAngle:state.rotation?.angle||270,camera:{...viewer.camera},rendererError:error};
 if(fields.kind!=='mesh'){observation.field=state.field;observation.compareField=state.compareField;observation.time=frame().time;}
 pendingViewerObservation={id:task.id,observation};if(viewerSyncTimer)return;
 viewerSyncTimer=setTimeout(()=>{viewerSyncTimer=null;const next=pendingViewerObservation;if(task?.id!==next.id)return;fetch(`${BASE}/api/tasks/${next.id}/viewer-state`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Workbench-Token':dsh.token},body:JSON.stringify(next.observation)}).catch(()=>{});},350);
}

function syncParameterValues(flush=false){clearTimeout(parameterSyncTimer);const id=task.id,values={...state.parameters};parameterSyncTimer=setTimeout(()=>{if(task?.id!==id)return;fetch(`${BASE}/api/tasks/${id}/parameter-values`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Workbench-Token':dsh.token},body:JSON.stringify(values)}).then(async r=>{if(!r.ok)throw new Error((await r.json()).error);}).catch(error=>notify(error.message));},flush?0:250);}

let tasks=[],task=null,fields=null,viewer=null,compareViewer=null,interval=null,loadToken=0,drawerView=null,drawerToken=0,toastTimer=null;
const fieldCache=new Map();
function syncAdaptiveChrome(){
 if(!adaptive?.active)return;
 els['export-button'].disabled=!adaptive.ready;els['export-field'].disabled=!adaptive.ready;els['export-history'].hidden=true;els['export-image-label'].textContent='展示面板截图';els['export-field-label'].textContent='面板数据';
 if(adaptive.replaces)els['study-overview'].hidden=true;
}
function syncAdaptiveUI(){
 if(!adaptive)return;
 const wasActive=adaptive.active;
 const selectedTask=task,selectedView=activeView(),selectedFields=fields,selectedModel=model,currentVersion=loadedVersion,views=currentViews();
 adaptive.update(selectedTask?.presentation?.ui||null,{
  taskId:selectedTask?.id||null,uiRevision:selectedTask?.presentation?.uiRevision||0,deliveryVersion:selectedTask?.deliveryVersion||0,
  dataKey:JSON.stringify([currentVersion,selectedTask?.study?.version,selectedTask?.deliveryVersion,state.panel,state.field,state.frame,state.view,state.run]),
  state:{...state},parameters:{...state.parameters},bounds:model?programContext():{},time:frame()?.time,timeUnit:model?.timeUnit,
  interactions:selectedTask?.presentation?.interactions||[],interactionRevision:selectedTask?.presentation?.interactionRevision||0,
  modelHidden:false,
  controls:availableControls().map(c=>({...c,options:c.id==='view'?viewOptions(c):c.id==='compareField'?(model?.fields||[]).map(f=>({value:f.id,label:f.label})):c.options})),
  getStudyData:async()=>studyData||await api(`/api/tasks/${selectedTask.id}/study`),
  study:studyData,
  imageURL:file=>`${BASE}/api/tasks/${selectedTask.id}/ui-image?file=${encodeURIComponent(file)}&revision=${selectedTask.presentation?.uiRevision||0}`,
  hasStudy:!!selectedTask?.study,
  getDataset:id=>api(`/api/tasks/${selectedTask.id}/ui-data?dataset=${encodeURIComponent(id)}&revision=${selectedTask.presentation?.uiRevision||0}`),
  getViewData:async id=>{
   const view=id?views.find(v=>v.id===id):selectedView;if(!view)throw new Error('当前面板数据源尚无模型交付');
   const key=`${selectedTask.id}:${view.version||selectedTask.modelVersion||selectedTask.resultVersion||0}:${view.id}`;
   const data=currentVersion===key&&selectedFields?selectedFields:await cached(fieldCache,selectedTask.id,`fields?view=${encodeURIComponent(view.id)}`,key);
   return{data,meta:currentVersion===key&&selectedModel?selectedModel:view.task};
  }
 });
 const placementKey=JSON.stringify([task?.id,adaptive.settingsGroups]);if(placementKey!==settingsPlacementKey){settingsPlacementKey=placementKey;if(els.drawer.open&&drawerView==='settings')renderSettings();}
 if(wasActive&&!adaptive.active)syncStudyChrome();
 syncAdaptiveChrome();
 presentationActivity?.update(task);
 frontendObserver?.schedule();
}
async function applyUIAction(action){
 if(!task)throw new Error('请先选择任务');
 const ident=task.id;
 if(action.type==='parameter'){
  const control=task.presentation?.controls?.find(c=>c.id===action.id&&c.parameter);if(!control)throw new Error('按钮引用的参数已不存在');
  state.parameters[action.id]=action.value;refresh();syncParameterValues(true);return;
 }
 if(action.type!=='view')throw new Error('未注册的界面动作');
 const next=action.state;
 if(next.view&&next.view!==state.view){state.view=next.view;overrides.set(`${task.id}:viewPinned`,true);await loadCurrentFields();}
 if(task?.id!==ident)return;
 if(task.study&&state.panel!=='model')await selectStudyPanel('model');
 if(task?.id!==ident)return;
 if(!fields||!model)await loadCurrentFields();
 if(task?.id!==ident)return;
 if(!fields||!model)throw new Error('当前任务尚无模型结果');
 for(const key of Object.keys(next))if(viewOptionBound(key))throw new Error('该选项由参数联动控制，请更新对应参数：'+key);
 if(next.time!==undefined){if(!fields.frames?.length)throw new Error('当前没有保存的时间帧');state.frame=nearestFrame(fields.frames,next.time);}
 const camera={};for(const[key,value]of Object.entries(next)){
  if(['zoom','yaw','tilt'].includes(key))camera[key]=value;
  else if(key==='revolve')state.rotation.enabled=value;
  else if(key==='revolveAngle')state.rotation.angle=value;
  else if(!['view','time'].includes(key)){state[key]=value;overrides.set(`${task.id}:${state.view}:${key}`,value);}
 }
 pendingCamera=camera;cameraDirectiveRevision++;refresh();if(next.cameraView&&Object.keys(camera).length===0)viewer?.reset();remember();
}
let rotationSource=null;
function sourceMesh(){const data=rotationSource||fields;return data?.kind==='mesh'?data.mesh:data?.meshes?.[data.frames?.[state.frame]?.mesh];}
function rotationAvailable(){return !!rotationProfile(sourceMesh());}
function rotationActive(){return rotationAvailable()&&state.rotation?.enabled===true;}
function displayGeometry(){return !rotationAvailable()?model?.geometry:rotationActive()?`轴对称旋转重建（${state.rotation.angle}°）`:model?.reconstruction?'二维截面':model?.geometry;}
function parameterDisplayValue(row){
 if(rotationAvailable()){
  if(/旋转.*角度/.test(row.label))return rotationActive()?state.rotation.angle+(row.unit?'':'°'):'未启用';
  if(row.label==='显示几何')return displayGeometry();
 }
 return row.value;
}
function renderedMesh(){const mesh=sourceMesh();return !rotationAvailable()?mesh:rotationActive()?revolveMesh(mesh,state.rotation.angle):meridionalMesh(mesh);}
async function rotationData(data,meta,version){
 if(!meta.reconstruction||rotationProfile(data.meshes?.[data.frames?.[0]?.mesh]))return data;
 // Older revolved deliveries can omit tiny, degenerate cap faces. Use the
 // matching real raw mesh instead of guessing those missing cell boundaries.
 const ident=task.id,ids=meta.fields.map(f=>f.id).join('|');
 const candidates=currentViews().filter(v=>v.id!==state.view&&v.kind===activeView()?.kind&&v.task.shape==='mesh'&&!v.task.reconstruction&&v.task.dimensionality===2&&v.task.cells===meta.cells&&v.task.fields.map(f=>f.id).join('|')===ids);
 for(const view of candidates){
  let raw;try{raw=await cached(fieldCache,ident,`fields?view=${encodeURIComponent(view.id)}`,`${ident}:${view.version}:${view.id}`);}catch{continue;}
  if(task?.id!==ident||version!==modelLoadKey())return data;
  if(raw.frames?.length!==data.frames.length||raw.frames.some((f,i)=>f.time!==data.frames[i].time||meta.fields.some(({id})=>f.fields[id]?.some((v,j)=>v!==data.frames[i].fields[id][j]))))continue;
  const mesh=raw.meshes[raw.frames[0].mesh],profile=rotationProfile(mesh);if(!profile)continue;
  const centres=data.meshes[data.frames[0].mesh].cellCenters,axis=profile.axis,radial=profile.radial;
  if(!centres||!mesh.cellCenters||mesh.cellCenters.some((p,i)=>{const q=centres[i];return !q||Math.abs(p[axis]-q[axis])>profile.tol*100||Math.abs(Math.hypot(...radial.map(k=>p[k]))-Math.hypot(...radial.map(k=>q[k])))>profile.tol*100;}))continue;
  return raw;
 }
 return data;
}
const icon=name=>`<svg aria-hidden="true"><use href="assets/icons.svg#${name}"/></svg>`;
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=x=>Math.abs(x)>=1e5||Math.abs(x)>0&&Math.abs(x)<0.01?x.toExponential(2):Math.abs(x)>=100?x.toFixed(1):Math.abs(x)>=1?x.toFixed(2):x.toFixed(3);
const clock=x=>Number(x).toLocaleString('en-US');
function clamp(n,a,b){return Math.max(a,Math.min(b,n));}
function remember(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{}}
function notify(text){els.toast.textContent=text;els.toast.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>els.toast.hidden=true,2500);}
function announce(text){els['live-region'].textContent=text;}
async function api(path){const response=await fetch(BASE+path,{credentials:'same-origin'});if(!response.ok)throw new Error('结果暂时无法读取，请重试。');return response.json();}
async function cached(cache,id,resource,key=id){if(cache.has(key))return cache.get(key);const pending=api(`/api/tasks/${id}/${resource}`).catch(e=>{cache.delete(key);throw e;});cache.set(key,pending);while(cache.size>3)cache.delete(cache.keys().next().value);return pending;}
function selectedField(){return model?.fields?.find(x=>x.id===state.field)||model?.fields?.[0];}
function activeRun(){return studyData?.runs.find(r=>r.id===state.run);}
function currentViews(){const all=task?.views||[];if(!task?.study)return all;const ids=activeRun()?.viewIds||[];return all.filter(v=>ids.includes(v.id));}
function activeView(){const views=currentViews();return views.find(v=>v.id===state.view)||views.find(v=>v.id===(activeRun()?.defaultView||task?.defaultView))||views[0];}
function modelVersion(){return activeView()?.version||task?.modelVersion||task?.resultVersion||0;}
function modelLoadKey(){return `${task.id}:${modelVersion()}:${activeView()?.id||''}`;}
function syncStudyChrome(){els['model-content'].hidden=false;const isStudy=!!task?.study;els['study-delivery-error'].hidden=!isStudy||!task.importError;els['study-delivery-error'].textContent=task?.importError||'';els['study-navigation'].hidden=!isStudy;if(!isStudy){els['study-overview'].hidden=true;els['study-model-context'].hidden=true;els['model-content'].hidden=false;}else if(studyData)studyPanel.setSelection(state.run,state.panel);els['export-button'].disabled=isStudy&&state.panel==='overview'?!studyData:!fields;els['export-image-label'].textContent=isStudy&&state.panel==='overview'?'分析图表':'模型截图';els['export-field-label'].textContent=isStudy&&state.panel==='overview'?'参数组数据':'当前场数据';els['export-field'].disabled=isStudy&&state.panel==='overview'?!studyData:!fields||fields.kind==='mesh';els['export-history'].hidden=isStudy&&state.panel==='overview'||!fields?.frames?.some(f=>Number.isFinite(f.release));updateStudyTime();syncAdaptiveUI();}
async function loadStudy(){if(!task?.study){studyData=null;studyKey=null;syncStudyChrome();return;}const ident=task.id,key=`${ident}:${task.study.version}`;if(studyKey===key)return;const data=await cached(studyCache,ident,'study',key);if(task?.id!==ident||key!==`${task.id}:${task.study.version}`||studyKey===key)return;studyData=data;studyKey=key;if(!data.runs.some(r=>r.id===state.run))state.run=data.defaultRun||data.runs.find(r=>r.viewIds.length)?.id||data.runs[0]?.id||null;if(!['overview','model'].includes(state.panel))state.panel='overview';const view=activeView();state.view=view?.id||null;studyPanel.setData(ident,data,state.run,state.panel);syncStudyChrome();remember();}
async function syncTaskContent(){await loadStudy();await loadCurrentFields();syncStudyChrome();}
async function selectStudyRun(id,options={}){if(!studyData?.runs.some(r=>r.id===id))return;stop();const carry=frame()&&model?{time:frame().time,unit:model.timeUnit||'s'}:pendingStudyTime;pendingStudyTime=carry?{...carry,task:task.id,run:id}:null;state.run=id;state.view=null;presentationKey=null;emptyModel();state.view=activeView()?.id||null;if(options.openModel){state.panel='model';if(els.drawer.open)els.drawer.close();}studyPanel.setSelection(state.run,state.panel);syncStudyChrome();remember();try{await loadCurrentFields();syncStudyChrome();if(els.drawer.open&&drawerView==='parameters')renderParameters();}catch(error){showError(error.message);}}
async function selectStudyPanel(panel){if(!studyData)return;stop();state.panel=panel;studyPanel.setSelection(state.run,panel);syncStudyChrome();remember();if(panel==='model')try{await loadCurrentFields();syncStudyChrome();}catch(error){showError(error.message);}}

function displayModel(){return {...(activeView()?.task||task),id:task.id,title:task.title};}
function availableControls(){
 const m=activeView()?.task||task,variables=m?.fields||[];
 return rangeControls(task?.presentation?.controls||[],currentProgram(),state.field).filter(c=>{
  if(c.parameter)return true;
  if(Object.hasOwn(currentProgram()?.options||{},c.id)||Object.hasOwn(currentProgram()?.style||{},c.id))return false;
  if(['compare','compareField'].includes(c.id))return variables.length>1;
  if(['scale','colorMin','colorMax'].includes(c.id))return variables.length>0;
  if(['palette','reversePalette'].includes(c.id)&&Object.hasOwn(currentProgram()?.fields?.[state.field]||{},c.id))return false;
  if(c.id==='axialScale')return m?.shape==='rod';
  if(['displayMode','sliceAxis','slicePosition'].includes(c.id))return !rotationActive()&&m?.shape==='mesh'&&m?.supportsSlice!==false;
  if(['cut','cutAngle'].includes(c.id))return !rotationActive()&&!m?.reconstruction&&(m?.shape!=='mesh'||m?.dimensionality!==1);
  if(c.id==='extrema')return !!variables.length&&m?.supportsExtrema===true;
  return true;
 }).map(c=>c.id==='cameraView'&&!c.parameter?{...c,default:c.default==='3d'?'auto':c.default,options:c.options?.filter(o=>o.value!=='3d')}:c);
}
function applyPresentation(){const key=task?`${task.id}:${task.presentationVersion||0}:${state.view||''}`:null;if(key===presentationKey){syncAdaptiveUI();return;}presentationKey=key;const nextParameters=JSON.stringify([task?.id,task?.presentation?.parameterRevision||0,(task?.presentation?.controls||[]).filter(c=>c.parameter)]);if(nextParameters!==parameterKey){clearTimeout(parameterSyncTimer);parameterKey=nextParameters;state.parameters=Object.fromEntries((task?.presentation?.controls||[]).filter(c=>c.parameter).map(c=>[c.id,task?.presentation?.parameterValues?.[c.id]??c.default]));}const nextRendering=JSON.stringify([task?.id,task?.presentation?.renderingRevision||0,task?.presentation?.rendering||{}]);if(nextRendering!==renderingKey){renderingKey=nextRendering;for(const name of overrides.keys())if(renderIds.some(id=>name.endsWith(':'+id)))overrides.delete(name);Object.assign(state,{scale:'fixed',scaleX:1,scaleY:1,scaleZ:1,palette:'coolwarm',reversePalette:false,opacity:1,background:'#fbfbfc',wireColor:'#5b6472',colorMin:0,colorMax:1});for(const[id,value]of Object.entries(renderingBindings()))if(value!==undefined)state[id]=value;}for(const c of availableControls()){if(c.parameter)continue;const name=`${task.id}:${state.view}:${c.id}`;if(c.id!=='view'){if(overrides.has(name))state[c.id]=overrides.get(name);else if(renderingBindings()[c.id]!==undefined)state[c.id]=renderingBindings()[c.id];else if(c.default!==undefined)state[c.id]=c.default;}}els['cut-button'].hidden=!availableControls().some(c=>c.id==='cut');syncViewerShortcuts();if(!fields&&task?.presentation?.parameters?.length){document.querySelector('.result-bar').hidden=false;document.querySelector('.result-metrics').hidden=true;els['parameters-button'].disabled=false;}if(els.drawer.open&&drawerView==='parameters')renderParameters();if(els.drawer.open&&drawerView==='settings')renderSettings();if(fields&&loadedVersion?.endsWith(`:${state.view||''}`))refresh();syncAdaptiveUI();}
function values(id=state.field){return fields.series?fields.frames[state.frame].fields[id]:fields[id];}
function frame(){return fields?.frames?.[state.frame];}
function timeText(){return frame()?`${clock(frame().time)} ${model?.timeUnit||'s'}`:'稳态';}
function mergeTask(meta){if(meta.draft)return;const i=tasks.findIndex(t=>t.id===meta.id);if(i<0)tasks.unshift(meta);else tasks[i]={...tasks[i],...meta};if(task?.id===meta.id){const directive=meta.presentation?.viewState||{},selectionKey=JSON.stringify([meta.id,meta.presentation?.viewStateRevision||0,directive]);if(directive.view&&selectionKey!==selectedViewDirectiveKey&&meta.views?.some(v=>v.id===directive.view)){selectedViewDirectiveKey=selectionKey;state.view=directive.view;overrides.set(`${meta.id}:viewPinned`,true);}if(!meta.study&&meta.defaultView&&meta.defaultView!==task.defaultView&&!overrides.has(`${meta.id}:viewPinned`))state.view=meta.defaultView;if(!meta.study&&!task.resultReady&&meta.resultReady){const current=(meta.views||[]).find(v=>v.id===state.view);if(current?.kind==='mesh')state.view=(meta.views||[]).find(v=>v.kind==='results'&&v.caseRoot===current.caseRoot)?.id||meta.defaultView;}task={...task,...meta};}taskMenu();updateHeading();applyPresentation();}
function updateHeading(){presentationActivity?.update(task);document.title=(task?.title||'OFFBEAT')+' · 计算工作台';execution?.setTask(task);delivery?.setTask(task);els['task-title'].textContent=task?.title||'新任务';els['process-button'].disabled=!task;els['task-picker'].disabled=!tasks.length;
 const progress=task?.progress,summary=progress?.summary||'';els['task-progress'].hidden=!summary;els['progress-summary'].textContent=summary;els['task-progress'].dataset.state=task?.status||'';els['task-progress'].title='计算流程与子过程，由执行事件及求解日志更新';els['progress-stages'].innerHTML=(progress?.stages||[]).map(s=>`<span class="progress-stage" data-state="${escape(s.status)}">${escape(s.label)}</span>`).join('');
}
function showDraft(){studyData=null;studyKey=null;syncStudyChrome();loadToken++;stop();task=null;model=null;presentationKey=null;studyData=null;syncStudyChrome();state.task=null;state.view=null;if(els.drawer.open)els.drawer.close();emptyModel();updateHeading();taskMenu();els['viewer-error'].hidden=true;els['loading-state'].hidden=true;els.workspace.setAttribute('aria-busy','false');remember();}
function rangeKey(){return `${task.id}:${state.view}:${state.field}`;}
function restoreCustomRange(){
 if(state.scale!=='custom'||!model?.fields?.some(f=>f.id===state.field))return;
 const bounds=customRanges.get(rangeKey())||model.fields.find(f=>f.id===state.field).range;
 [state.colorMin,state.colorMax]=bounds;
}
function range(id=state.field){return resolveRange({bound:bindField(currentProgram(),id,state.parameters,programContext()).range,declared:task?.presentation?.rendering?.fields?.[id]?.range,manual:overrides.has(`${task.id}:${state.view}:scale`),scale:id===state.field?state.scale:state.scale==='custom'?'fixed':state.scale,custom:[state.colorMin,state.colorMax],fixed:model.fields.find(f=>f.id===id).range,values:values(id)});}

function sampler(rs,vs){return r=>{let lo=0,hi=rs.length-1;while(lo<hi){const m=(lo+hi)>>1;if(rs[m]<r)lo=m+1;else hi=m;}if(lo&&Math.abs(rs[lo-1]-r)<Math.abs(rs[lo]-r))lo--;return vs[lo];};}
function closeMenus(){for(const el of [els['task-menu'],els['export-menu']])if(el.matches(':popover-open'))el.hidePopover();}
function positionMenu(menu,anchor,align='left'){if(!menu.matches(':popover-open'))return;const rect=anchor.getBoundingClientRect(),width=menu.offsetWidth;menu.style.left=`${clamp(align==='right'?rect.right-width:rect.left,8,Math.max(8,window.innerWidth-width-8))}px`;menu.style.top=`${Math.min(rect.bottom+9,window.innerHeight-menu.offsetHeight-10)}px`;}
for(const [menu,anchor,alignment] of [[els['task-menu'],els['task-picker'],'left'],[els['export-menu'],els['export-button'],'right']])menu.addEventListener('toggle',()=>positionMenu(menu,anchor,alignment));
window.addEventListener('resize',()=>{positionMenu(els['task-menu'],els['task-picker']);positionMenu(els['export-menu'],els['export-button'],'right');});

function taskMenu(){els['task-menu-items'].innerHTML=tasks.map(t=>`<button class="menu-item ${t.id===state.task?'current':''}" data-select-task="${t.id}">${icon(t.shape==='rod'?'rod':'sphere')}<span class="menu-task-name">${escape(t.title)}</span><span>${statusLabel[t.status]||'等待执行'}</span></button>`).join('');}
async function loadCurrentFields(){
 if(task?.study&&state.panel==='model'&&!activeView()){emptyModel();return;}
 if(!task?.modelReady&&!task?.resultReady||!activeView())return;const targetTime=pendingStudyTime&&pendingStudyTime.task===task.id&&pendingStudyTime.run===state.run?pendingStudyTime:frame()&&model?{time:frame().time,unit:model.timeUnit||'s'}:null;const ident=task.id,view=activeView();state.view=view?.id||null;applyPresentation();const version=modelLoadKey();if(loadedVersion===version)return;
 const followLatest=(task.status==='running'||activeRun()?.status==='running')&&!pendingStudyTime&&(!fields||fields.kind==='mesh'||loadedVersion?.endsWith(':'+state.view)&&state.frame===fields.frames?.length-1);
 const data=await cached(fieldCache,ident,'fields'+(state.view?`?view=${encodeURIComponent(state.view)}`:''),version);if(task?.id!==ident||version!==modelLoadKey()||loadedVersion===version)return;
 const nextModel=displayModel(),rotation=await rotationData(data,nextModel,version);if(task?.id!==ident||version!==modelLoadKey())return;
 stop();if(fields?.kind==='mesh'&&data.kind!=='mesh')viewDirectiveKey=null;fields=data;model=nextModel;rotationSource=rotation;loadedVersion=version;const geometryOnly=data.kind==='mesh',rotationKey=task.id+':'+state.view;if(state.rotation?.key!==rotationKey)state.rotation={key:rotationKey,enabled:!!model.reconstruction,angle:model.reconstruction?.angle||270};state.rotation.angle=clamp(Number(state.rotation.angle)||270,1,360);
 if(!geometryOnly){if(!model.fields.some(x=>x.id===state.field))state.field=model.fields[0].id;state.frame=followLatest?data.frames.length-1:targetTime?(targetTime.unit===(model.timeUnit||'s')?nearestFrame(data.frames,targetTime.time):0):clamp(Number.isInteger(state.frame)?state.frame:0,0,data.frames.length-1);pendingStudyTime=null;}
 els['field-select'].innerHTML=geometryOnly?'<option>网格预览</option>':model.fields.map(f=>`<option value="${escape(f.id)}">${escape(f.label)}</option>`).join('');if(!geometryOnly)els['field-select'].value=state.field;
 if(!geometryOnly){if(!model.fields.some(f=>f.id===state.compareField))state.compareField=model.fields.find(f=>f.id!==state.field)?.id||state.field;els['compare-field-select'].innerHTML=model.fields.map(f=>`<option value="${escape(f.id)}">${escape(f.label)}</option>`).join('');els['compare-field-select'].value=state.compareField;}
 els['field-select'].disabled=geometryOnly;els['export-button'].disabled=false;els['export-field'].disabled=geometryOnly;els['parameters-button'].disabled=false;els['empty-model'].hidden=true;els['model-stage'].classList.remove('unready');els['model-stage'].classList.toggle('mesh-preview',geometryOnly);document.querySelector('.result-bar').hidden=false;document.querySelector('.result-metrics').hidden=geometryOnly;
 const sequence=!geometryOnly&&data.frames.length>1;els['time-panel'].hidden=!sequence;
 if(sequence){els['time-range'].max=data.frames.length-1;els['time-start'].textContent=`${clock(data.frames[0].time)} ${model.timeUnit||'s'}`;els['time-end'].textContent=`${clock(data.frames.at(-1).time)} ${model.timeUnit||'s'}`;}
 els['export-history'].hidden=geometryOnly||!data.frames?.some(f=>Number.isFinite(f.release));if(!geometryOnly)restoreCustomRange();refresh();remember();if(els.drawer.open&&drawerView==='settings')renderSettings();
}
function emptyModel(){fields=null;model=null;rotationSource=null;loadedVersion=null;viewer?.clear();compareViewer?.clear();els['model-stage'].classList.remove('comparing');for(const id of ['compare-canvas','compare-picker','compare-legend'])els[id].hidden=true;els['model-stage'].classList.add('unready');els['empty-model'].hidden=false;els['empty-model-label'].textContent=!task?'在右侧 DSH 描述计算任务':task.study?(activeRun()?.status==='failed'?'本组求解失败，未展示其他组的结果':activeRun()?.status==='completed'?'本组尚未交付模型':'本组模型尚未就绪'):task.status==='failed'?'查看 DSH 执行记录':'等待模型结果';els['field-select'].disabled=true;els['export-button'].disabled=true;els['parameters-button'].disabled=true;document.querySelector('.result-bar').hidden=!task?.presentation?.parameters?.length;document.querySelector('.result-metrics').hidden=true;els['parameters-button'].disabled=!task?.presentation?.parameters?.length&&!studyData;els['time-panel'].hidden=true;syncAdaptiveUI();}
async function showTask(id){const selected=tasks.find(t=>t.id===id);if(!selected)return;const token=++loadToken;stop();closeMenus();if(els.drawer.open)els.drawer.close();if(state.task!==id){Object.assign(state,{cut:false,mesh:false,compare:false,displayMode:'surface',cameraView:'auto',aspectMode:'physical',scale:'fixed',extrema:false,extremaMode:'both'});pendingCamera={};viewDirectiveKey=null;cameraDirectiveRevision++;cameraPresetRevision++;pendingStudyTime=null;state.frame=0;if(state.task)studySelections.set(state.task,{run:state.run,panel:state.panel});state.view=null;presentationKey=null;Object.assign(state,studySelections.get(id)||{run:null,panel:'overview'});}studyData=null;studyKey=null;task=selected;state.task=id;syncStudyChrome();emptyModel();updateHeading();taskMenu();els['loading-state'].hidden=false;els['viewer-error'].hidden=true;els.workspace.setAttribute('aria-busy','true');
 try{await dsh.select(task);if(token!==loadToken)return;await syncTaskContent();remember();announce(`${task.title}，${statusLabel[task.status]||'已完成'}`);}catch(error){if(token===loadToken)showError(error.message);}finally{if(token===loadToken){els['loading-state'].hidden=true;els.workspace.setAttribute('aria-busy','false');}}
}
function showError(message){els['viewer-error'].textContent=message;els['viewer-error'].hidden=false;syncViewerState(message);}
function updateStudyTime(){if(task?.study&&state.panel==='model'&&fields?.frames?.length&&activeRun())els['study-model-context'].textContent=runLabel(studyData,activeRun())+' · '+timeText();}
function syncUniformLegend(legend,actual,unit){
 let note=legend.querySelector('.uniform-field-note');if(!note){note=document.createElement('span');note.className='uniform-field-note';legend.append(note);}
 note.hidden=!actual.uniform;note.textContent=actual.uniform?`当前保存场全域均匀 · ${actual.min} ${unit}`:'';
 legend.querySelector('.legend-gradient').hidden=actual.uniform;legend.querySelector('.legend-numbers').hidden=actual.uniform;
}
function refresh(){if(!task||!fields||!viewer||!model)return;try{const programOptions=applyProgramOptions(),geometryOnly=fields.kind==='mesh',comparing=!geometryOnly&&state.compare&&model.fields.length>1;
 els['model-stage'].classList.toggle('comparing',comparing);for(const id of ['compare-canvas','compare-picker','compare-legend'])els[id].hidden=!comparing;
 const mesh=model.shape==='mesh'?renderedMesh():null,revolved=!!mesh?.reconstruction,geometry=displayGeometry(),displayedModel={...model,geometry,reconstruction:mesh?.reconstruction};
 const mode=state.cameraView==='auto'?(revolved?'3d':model.shape==='mesh'&&state.displayMode==='slice'?{x:'yz',y:'xz',z:'xy'}[state.sliceAxis]:mesh?.preferredView||model.preferredView||'3d'):state.cameraView;
 els['model-stage'].style.background=renderStyle().background;const render=(v,id)=>{v.setDisplayProgram(currentProgram(),state.parameters);v.setStyle(renderStyle(id));v.cut=state.cut&&!revolved&&(model.shape!=='mesh'||model.dimensionality!==1);v.mesh=state.mesh;v.cutAngle=state.cutAngle;v.axialScale=state.axialScale;v.displayMode=model.shape==='mesh'&&model.supportsSlice!==false?state.displayMode:'surface';v.sliceAxis=state.sliceAxis;v.slicePosition=state.slicePosition;v.aspectMode=state.aspectMode;if(v.cameraPresetRevision!==programOptions.cameraPresetRevision){v.camera.zoom=1;v.setView(mode,true);v.cameraPresetRevision=programOptions.cameraPresetRevision;}else v.setView(mode);v.setProgramCamera(programOptions);const key=`${task.id}:${state.view}:${modelVersion()}:${revolved?state.rotation.angle:'flat'}`;if(geometryOnly)v.setMeshPreview(displayedModel,mesh,key);else if(model.shape==='mesh')v.setNativeModel(displayedModel,mesh,values(id),range(id),`${key}:${frame().mesh}`);else v.setModel(model,sampler(fields.r,values(id)),range(id),key);v.setAnnotations(!geometryOnly&&state.extrema,!geometryOnly?values(id):[],model.fields?.find(f=>f.id===id)?.unit||'',fields.r,state.extremaMode);v.setSceneAnnotations(geometryOnly?null:currentProgram(),state.parameters,geometryOnly?{}:frame()?.fields||fields,model.fields||[],id);};
 try{render(viewer,state.field);if(comparing){render(compareViewer,state.compareField);compareViewer.camera={...viewer.camera};compareViewer.draw();}else compareViewer?.clear();els['viewer-error'].hidden=true;}catch(error){showError(error.message);return;}
 els['cut-button'].disabled=model.shape==='mesh'&&state.displayMode==='slice';els['cut-button'].setAttribute('aria-pressed',String(state.cut));syncViewerShortcuts();
 if(geometryOnly){drawAxis();syncViewerState();syncAdaptiveUI();return;}
 const variable=selectedField(),vs=values(),bounds=range();els['legend-symbol'].textContent=variable.symbol;els['legend-unit'].textContent=variable.unit;els['legend-min'].textContent=fmt(bounds[0]);els['legend-max'].textContent=fmt(bounds[1]);const actual=fieldSummary(vs);els['metric-max'].textContent=fmt(actual.max);els['metric-min'].textContent=fmt(actual.min);syncUniformLegend(els['legend'],actual,variable.unit);document.querySelectorAll('.metric-unit').forEach(el=>el.textContent=variable.unit);
 els['legend'].querySelector('.legend-gradient').style.background=gradient(renderStyle().palette,renderStyle().reversePalette);if(comparing){els['compare-legend'].querySelector('.legend-gradient').style.background=gradient(renderStyle(state.compareField).palette,renderStyle(state.compareField).reversePalette);const other=model.fields.find(f=>f.id===state.compareField),r=range(state.compareField);els['compare-symbol'].textContent=other.label;els['compare-unit'].textContent=other.unit;els['compare-min'].textContent=fmt(r[0]);els['compare-max'].textContent=fmt(r[1]);els['compare-field-select'].value=state.compareField;syncUniformLegend(els['compare-legend'],fieldSummary(values(state.compareField)),other.unit);}
 document.querySelectorAll('[data-extrema-metric]').forEach(el=>el.hidden=!state.extrema);
 els['release-metric'].hidden=!Number.isFinite(frame()?.release);if(frame()){els['time-value'].innerHTML=`${clock(frame().time)} <small>${escape(model.timeUnit||'s')}</small>`;els['time-range'].value=state.frame;els['frame-count'].textContent=`${state.frame+1} / ${fields.frames.length}`;if(Number.isFinite(frame().release))els['metric-release'].textContent=`${(frame().release*100).toFixed(2)}%`;}
 document.querySelector('.result-metrics').hidden=!state.extrema&&!Number.isFinite(frame()?.release);updateStudyTime();drawAxis();syncViewerState();syncAdaptiveUI();
}catch(error){showError(error.message);}
}
function drawAxis(){if(!viewer)return;els['axis-svg'].innerHTML=[['X',[1,0,0]],['Y',[0,1,0]],['Z',[0,0,1]]].map(([name,p])=>{const[x,z]=viewer.projectAxis(p);return `<line x1="35" y1="39" x2="${35+x*23}" y2="${39-z*23}" stroke="#8ca5ca"/><text x="${35+x*30}" y="${42-z*30}" fill="#7894be" stroke="none" text-anchor="middle" font-size="10" font-family="system-ui">${name}</text>`;}).join('');}
function stop(){if(interval){clearInterval(interval);interval=null;}els['play-button'].innerHTML=icon('play');els['play-button'].setAttribute('aria-label','播放时间序列');}
function play(){if(!task||!fields?.frames||fields.frames.length<=1)return;if(interval){stop();remember();return;}if(state.frame===fields.frames.length-1)state.frame=0;refresh();els['play-button'].innerHTML=icon('pause');els['play-button'].setAttribute('aria-label','暂停时间序列');interval=setInterval(()=>{if(state.frame>=fields.frames.length-1){stop();remember();announce('已播放至最终时刻');return;}state.frame++;refresh();},500);}

function openDrawer(view){
 if(!task&&view!=='tasks')return;stop();closeMenus();drawerView=view;els.drawer.dataset.view=view;drawerToken++;
 const inspecting=['settings','parameters'].includes(view);
 els['drawer-title'].textContent={tasks:'计算任务',settings:'显示设置',parameters:'模型参数',runs:'参数组'}[view];els['drawer-content'].replaceChildren();
 if(els.drawer.open&&els.drawer.matches(':modal')===inspecting)els.drawer.close();
 if(!els.drawer.open){if(inspecting)els.drawer.show();else els.drawer.showModal();}
 if(view==='runs')studyPanel.renderRuns(els['drawer-content'],studyPanel.pendingBinIds);if(view==='tasks')renderTasks();if(view==='settings')renderSettings();if(view==='parameters')renderParameters();
 syncDrawerTriggers();
}
function syncDrawerTriggers(){for(const view of ['settings','parameters'])els[view+'-button'].setAttribute('aria-expanded',String(els.drawer.open&&drawerView===view));}
function toggleDrawer(view){if(els.drawer.open&&drawerView===view)els.drawer.close();else openDrawer(view);}
function renderTasks(){els['drawer-content'].innerHTML=`<p class="drawer-note">${tasks.length} 个任务</p>`+tasks.map(t=>`<button class="task-card ${task.id===t.id?'current':''}" data-select-task="${t.id}"><span class="task-card-icon">${icon(t.shape==='rod'?'rod':'sphere')}</span><span><strong>${escape(t.title)}</strong><small>${statusLabel[t.status]||'已完成'}${t.cells?' · '+t.cells+' 单元':''}</small></span>${task.id===t.id?icon('check'):''}</button>`).join('');}
function renderParameters(){let sections=task.presentation?.parameters||[{title:'模型参数',items:((model||task).parameters||[]).map(([label,value])=>({label,value,unit:''}))}];if(studyData&&activeRun()){const r=activeRun();sections=[{title:'当前参数组 · '+runLabel(studyData,r),items:studyData.parameters.map(d=>({label:d.label,value:d.type==='category'?r.parameters[d.id]??'—':displayNumber(r.parameters[d.id]),unit:d.unit}))},{title:'本组响应',items:studyData.responses.map(d=>({label:d.label,value:displayNumber(r.responses[d.id]),unit:d.unit}))},...sections];}els['drawer-content'].innerHTML=sections.length?sections.map(section=>`<section class="parameter-group">${section.title?`<h3>${escape(section.title)}</h3>`:''}<dl class="parameter-list">${section.items.map(row=>`<div><dt>${escape(row.label)}</dt><dd>${escape(parameterDisplayValue(row))}${row.unit?' '+escape(row.unit):''}</dd></div>`).join('')}</dl></section>`).join(''):'<p class="drawer-note">尚未发布模型参数</p>';}
function viewOptions(control){const views=currentViews();if(!control.options?.length)return views.map(v=>({value:v.id,label:v.label}));const rows=[];for(const option of control.options){const exact=views.find(v=>v.id===option.value);if(exact){rows.push({value:exact.id,label:option.label});continue;}let matches=views.filter(v=>v.task.shape===option.value);const results=matches.filter(v=>v.kind==='results');if(results.length)matches=results;for(const v of matches)rows.push({value:v.id,label:matches.length===1?option.label:v.label});}return rows.length?[...new Map(rows.map(o=>[o.value,o])).values()]:views.map(v=>({value:v.id,label:v.label}));}
function renderSettings(){
 const rows=availableControls().filter(c=>c.parameter||!model||!fields||!['mesh','cameraView','extrema','compare'].includes(c.id)).filter(c=>c.parameter||!['scaleX','scaleY','scaleZ'].includes(c.id)||showScaleControls(task?.presentation?.rendering,[state.scaleX,state.scaleY,state.scaleZ])).filter(c=>c.parameter||!['sliceAxis','slicePosition'].includes(c.id)||state.displayMode==='slice').filter(c=>c.parameter||c.id!=='compareField'||state.compare).filter(c=>c.parameter||!['colorMin','colorMax'].includes(c.id)||state.scale==='custom').filter(c=>c.parameter||!['cut','cutAngle'].includes(c.id)||state.displayMode!=='slice');
 els['drawer-title'].textContent='显示设置';
 renderParameterPanel(els['drawer-content'],groupSettingsControls(rows,adaptive?.settingsGroups||[],task?.presentation?.ui).map(c=>c.parameter?c:{...c,options:c.id==='view'?viewOptions(c):c.id==='compareField'?(model?.fields||[]).map(f=>({value:f.id,label:f.label})):c.options}),c=>c.parameter?state.parameters[c.id]:c.id==='view'?(state.view||task.defaultView):c.id==='palette'?renderStyle().palette:c.id==='reversePalette'?renderStyle().reversePalette:state[c.id]);
 if(model&&fields){if(!rows.length)els['drawer-content'].replaceChildren();els['drawer-content'].insertAdjacentHTML('afterbegin',viewerShortcuts()+rotationControls());syncViewerShortcuts();}
 if(task?.presentation?.panelDescription)els['drawer-content'].insertAdjacentHTML('afterbegin',`<p class="drawer-note">${escape(task.presentation.panelDescription)}</p>`);
}

function viewOptionBound(id){return Object.hasOwn(currentProgram()?.options||{},id);}
function rotationControls(){
 if(!rotationAvailable())return '';
 const enabled=rotationActive(),angle=state.rotation.angle,lockRotation=viewOptionBound('revolve')?'disabled title="由当前参数联动控制"':'',lockAngle=viewOptionBound('revolveAngle')?'disabled title="由当前参数联动控制"':'';
 return `<section class="rotation-controls" aria-label="二维旋转模型"><label class="setting-row"><span>旋转模型</span><input type="checkbox" data-rotation-enabled ${lockRotation} ${enabled?'checked':''}></label><div class="rotation-angle" ${enabled?'':'hidden'}><label for="rotation-angle">旋转角度</label><div><input id="rotation-angle" type="range" data-rotation-angle ${lockAngle} min="1" max="360" step="1" value="${angle}"><input type="number" data-rotation-angle ${lockAngle} aria-label="旋转角度（度）" min="1" max="360" step="1" value="${angle}"><span>°</span></div></div></section>`;
}
function viewerShortcuts(){
 const toggles=[['mesh','mesh','网格'],...(fields.kind!=='mesh'&&model.supportsExtrema?[['extrema','focus','极值标注']]:[]),...(fields.kind!=='mesh'&&model.fields.length>1?[['compare','table','双变量']]:[])];
  return `<section class="viewer-shortcuts" aria-label="常用显示操作"><h3>快捷操作</h3><div class="viewer-shortcut-row">${toggles.map(([id,symbol,label])=>`<button type="button" data-view-toggle="${id}" aria-pressed="${!!state[id]}">${icon(symbol)}${label}</button>`).join('')}</div><div class="viewer-shortcut-row" aria-label="观察方向">${[['auto','自动'],['xy','XY'],['xz','XZ'],['yz','YZ']].map(([value,label])=>`<button type="button" data-camera-view="${value}" aria-label="${label}视角" aria-pressed="${state.cameraView===value}">${label}</button>`).join('')}</div><div class="viewer-shortcut-row"><button type="button" data-view-action="reset">${icon('focus')}复位视角</button><button type="button" data-view-action="image">${icon('image')}模型截图</button></div></section>`;
}
function syncViewerShortcuts(){
 els['settings-button'].disabled=!model&&!availableControls().length;
 document.querySelector('.viewer-tools').hidden=els['cut-button'].hidden;
 const views=els['drawer-content'].querySelector('select[data-control="view"]');
 if(views&&rotationAvailable()&&availableControls().some(c=>c.id==='view'&&!c.parameter))for(const option of views.options)if(option.value===state.view)option.textContent=displayGeometry();
 for(const button of els['drawer-content'].querySelectorAll('[data-view-toggle],[data-camera-view]')){
  const key=button.dataset.viewToggle||'cameraView';button.disabled=viewOptionBound(key);button.title=button.disabled?'由当前参数联动控制':'';button.setAttribute('aria-pressed',String(button.dataset.viewToggle?!!state[key]:state.cameraView===button.dataset.cameraView));
 }
}
function setViewerOption(key,value){
 if(!task||!model||!fields||viewOptionBound(key))return;state[key]=value;overrides.set(`${task.id}:${state.view}:${key}`,value);if(key==='cameraView'){pendingCamera={};cameraDirectiveRevision++;}refresh();if(key==='cameraView')viewer?.reset();remember();if(els.drawer.open&&drawerView==='settings')renderSettings();
}


function fileTitle(){return ((task?.title||'计算结果')+(task?.study&&state.panel==='model'&&activeRun()?'_'+runLabel(studyData,activeRun()):'')).replace(/[\\/:*?"<>|]/g,'_');}
function download(blob,name){const link=document.createElement('a'),url=URL.createObjectURL(blob);link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function exportCSV(history=false){if(adaptive?.active&&!history){try{download(adaptive.csv(),`${fileTitle()}_面板数据.csv`);closeMenus();}catch(error){notify(error.message);}return;}if(task?.study&&state.panel==='overview'){download(new Blob([studyPanel.csv()],{type:'text/csv;charset=utf-8'}),`${fileTitle()}_参数组.csv`);closeMenus();return;}if(!task||!fields||fields.kind==='mesh')return;let rows,name;if(history&&fields.frames?.some(f=>Number.isFinite(f.release))){rows=[['time_s','cumulative_release_fraction'],...fields.frames.map(f=>[f.time,f.release])];name=`${fileTitle()}_release_history.csv`;}else{const f=selectedField();rows=[[model.profileAxis==='cell'?'cell_id':`r_${model.radialUnit==='μm'?'um':model.radialUnit||'mm'}`,`${f.id} [${f.unit}]`],...fields.r.map((r,i)=>[r,values()[i]])];name=`${fileTitle()}_${f.id}_${frame()?frame().time:'steady'}.csv`;}download(new Blob(['\uFEFF'+rows.map(row=>row.join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),name);closeMenus();notify('已导出 CSV');}
async function exportImage(){if(adaptive?.active){try{download(await adaptive.image(),`${fileTitle()}_展示面板.png`);closeMenus();}catch(error){notify(error.message);}return;}if(task?.study&&state.panel==='overview'){try{const blob=await studyPanel.image();if(blob)download(blob,`${fileTitle()}_分析图.png`);}catch(error){notify(error.message);}closeMenus();return;}if(!task||!viewer||!fields)return;const compared=state.compare&&model.fields.length>1&&fields.kind!=='mesh',sources=compared?[viewer.screenshot(),compareViewer.screenshot()]:[viewer.screenshot()],width=sources.reduce((n,c)=>n+c.width,0),height=Math.max(...sources.map(c=>c.height)),out=document.createElement('canvas'),ctx=out.getContext('2d');out.width=width;out.height=height+110;ctx.fillStyle=renderStyle().background;ctx.fillRect(0,0,width,out.height);let x=0;for(let i=0;i<sources.length;i++){const source=sources[i];ctx.drawImage(source,x,0);ctx.fillStyle='#476a9c';ctx.font=`${Math.max(16,width/85)}px "Workbench CJK",system-ui`;ctx.fillText(task.title,x+20,height+30);if(fields.kind==='mesh'){ctx.fillText(`网格预览 · ${model.cells} 单元`,x+20,height+65);}else{const id=i?state.compareField:state.field,f=model.fields.find(v=>v.id===id),r=range(id);ctx.font=`${Math.max(12,width/115)}px "Workbench CJK",system-ui`;ctx.fillText(`${currentProgram()?.vertex?currentProgram().label+'（显示变换） · ':''}${rotationActive()||model.reconstruction?displayGeometry()+' · ':''}${displayScaleText()?displayScaleText()+' · ':''}${f.label} [${f.unit}] · ${timeText()}${state.aspectMode==='fit'&&viewer.viewMode!=='3d'?' · 坐标缩放':''}`,x+20,height+55);const g=ctx.createLinearGradient(x+20,0,x+source.width-20,0);const style=renderStyle(id);for(const[t,color]of stops(style.palette))g.addColorStop(style.reversePalette?1-t:t,color);ctx.fillStyle=g;ctx.fillRect(x+20,height+70,source.width-40,6);ctx.fillStyle='#7d94b7';ctx.fillText(fmt(r[0]),x+20,height+96);ctx.textAlign='right';ctx.fillText(fmt(r[1]),x+source.width-20,height+96);ctx.textAlign='left';}x+=source.width;}out.toBlob(blob=>{if(blob){download(blob,`${fileTitle()}_${compared?'compare':fields.kind==='mesh'?'mesh':state.field}.png`);notify('已导出模型截图');}else notify('截图导出失败，请重试。');},'image/png');closeMenus();}

els['all-tasks-menu'].addEventListener('click',()=>openDrawer('tasks'));els['parameters-button'].addEventListener('click',()=>toggleDrawer('parameters'));els['settings-button'].addEventListener('click',()=>toggleDrawer('settings'));els['close-drawer'].addEventListener('click',()=>els.drawer.close());els.drawer.addEventListener('close',()=>{if(!els.drawer.open){drawerView=null;drawerToken++;syncDrawerTriggers();}});els.drawer.addEventListener('click',e=>{if(e.target!==els.drawer||!els.drawer.matches(':modal'))return;const box=els.drawer.getBoundingClientRect();if(e.clientX<box.left||e.clientX>box.right)els.drawer.close();});
document.addEventListener('click',e=>{const button=e.target.closest('[data-select-task]');if(button)showTask(button.dataset.selectTask);});
els['drawer-content'].addEventListener('click',e=>{
 const button=e.target.closest('[data-view-toggle],[data-camera-view],[data-view-action]');if(!button||button.disabled)return;
 if(button.dataset.viewToggle)setViewerOption(button.dataset.viewToggle,!state[button.dataset.viewToggle]);
 else if(button.dataset.cameraView)setViewerOption('cameraView',button.dataset.cameraView);
 else if(button.dataset.viewAction==='reset')viewer?.reset();
 else if(button.dataset.viewAction==='image')exportImage();
});
els['drawer-content'].addEventListener('input',e=>{
 if(e.target.hasAttribute('data-rotation-enabled')){
  state.rotation.enabled=e.target.checked;if(state.rotation.enabled)state.displayMode='surface';
  if(!viewOptionBound('cameraView')){state.cameraView='auto';overrides.set(`${task.id}:${state.view}:cameraView`,'auto');}
  refresh();remember();renderSettings();
 }else if(e.target.hasAttribute('data-rotation-angle')){
  const angle=Number(e.target.value);if(e.target.value===''||!Number.isFinite(angle)||angle<1||angle>360)return;
  state.rotation.angle=angle;for(const input of els['drawer-content'].querySelectorAll('[data-rotation-angle]'))if(input!==e.target)input.value=angle;
  refresh();remember();
 }
});
async function handleControlInput(e){
 const key=e.target.dataset.control;if(!key)return;const c=availableControls().find(c=>c.id===key);if(!c)return;
 // Selects and toggles commit on change; number/range edits remain immediate.
 if(e.type==='input'&&['select','toggle'].includes(c.type))return;
 const value=c.type==='toggle'?e.target.checked:['range','number'].includes(c.type)?Number(e.target.value):e.target.value;
 if(['number','range'].includes(c.type)&&(!Number.isFinite(value)||value<c.min||value>c.max||e.target.value===''))return;
 if(c.parameter){state.parameters[key]=value;for(const output of document.querySelectorAll('[data-control-output]'))if(output.dataset.controlOutput===key)output.textContent=value;refresh();syncParameterValues(e.type==='change');return;}
 if((key==='colorMin'&&value>=state.colorMax)||(key==='colorMax'&&value<=state.colorMin)){notify('色标下限须小于上限');return;}
 if(key==='scale'&&value==='custom'){[state.colorMin,state.colorMax]=customRanges.get(rangeKey())||range();}
 overrides.set(`${task.id}:${state.view}:${key}`,value);
 if(key==='view'){
  const previous=state.view;overrides.set(`${task.id}:viewPinned`,true);state.view=value;
  try{await loadCurrentFields();remember();if(els.drawer.open&&drawerView==='settings')renderSettings();}
  catch(error){if(state.view===value){state.view=previous;await loadCurrentFields();renderSettings();}notify(error.message);}
  return;
 }
 state[key]=value;
 if(['colorMin','colorMax'].includes(key))customRanges.set(rangeKey(),[state.colorMin,state.colorMax]);
 if(['compare','displayMode','scale'].includes(key)&&els.drawer.open&&drawerView==='settings')renderSettings();
 for(const output of document.querySelectorAll('[data-control-output]'))if(output.dataset.controlOutput===key)output.textContent=value;
 refresh();remember();
}
els['drawer-content'].addEventListener('input',handleControlInput);
function handleControlChange(e){const c=availableControls().find(c=>c.id===e.target.dataset.control);if(['select','toggle'].includes(c?.type))void handleControlInput(e);else if(c?.parameter)syncParameterValues(true);}
els['drawer-content'].addEventListener('change',handleControlChange);
els['compare-field-select'].addEventListener('change',()=>{state.compareField=els['compare-field-select'].value;refresh();remember();});
els['field-select'].addEventListener('change',()=>{state.field=els['field-select'].value;restoreCustomRange();refresh();remember();if(els.drawer.open&&drawerView==='settings')renderSettings();announce(`${selectedField().label}，单位 ${selectedField().unit}`);});
els['cut-button'].addEventListener('click',()=>{state.cut=!state.cut;overrides.set(`${task.id}:${state.view}:cut`,state.cut);refresh();remember();});els['zoom-in'].addEventListener('click',()=>viewer?.zoom(1.15));els['zoom-out'].addEventListener('click',()=>viewer?.zoom(1/1.15));els['reset-view'].addEventListener('click',()=>viewer?.reset());els['play-button'].addEventListener('click',play);
els['time-range'].addEventListener('input',()=>{stop();state.frame=Number(els['time-range'].value);refresh();});els['time-range'].addEventListener('change',()=>{remember();announce(`求解时间 ${timeText()}`);});
els['export-image'].addEventListener('click',exportImage);els['export-field'].addEventListener('click',()=>exportCSV());els['export-history'].addEventListener('click',()=>exportCSV(true));
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&els.drawer.open&&drawerView!=='settings'&&!els.drawer.matches(':modal'))els.drawer.close();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();remember();}});

async function loadTasks(){tasks=(await api('/api/tasks')).filter(t=>!t.draft);if(tasks.length)await showTask(tasks.some(t=>t.id===state.task)?state.task:tasks[0].id);else await dsh.newTask();}
async function init(){try{
 presentationActivity=new PresentationActivity(els['presentation-skeletons']);
 frontendObserver=new FrontendStateObserver({context:()=>({task,state,adaptive,style:task&&model&&fields?renderStyle():null}),send:(id,observation)=>{if(dsh?.token)return fetch(`${BASE}/api/tasks/${id}/ui-state`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Workbench-Token':dsh.token},body:JSON.stringify(observation)}).catch(()=>{});}});
 adaptive=new AdaptiveUI({host:els['adaptive-ui'],aside:els['adaptive-aside'],model:els['model-content'],onAction:applyUIAction,onRun:selectStudyRun,onControlInput:handleControlInput,onControlChange:handleControlChange,onRendered:()=>{syncAdaptiveChrome();presentationActivity.update(task);frontendObserver.schedule();},getModelImage:()=>viewer?.screenshot(),onObserve:()=>frontendObserver.schedule()});
 studyPanel=new StudyPanel({onRun:selectStudyRun,onPanel:selectStudyPanel,onRuns:ids=>{studyPanel.pendingBinIds=ids||null;openDrawer('runs');},onError:showError});
 delivery=new DeliveryBrowser(els['delivery-panel']);
 execution=new ExecutionProcess({button:els['process-button'],panel:els['execution-process'],workspace:els.workspace,statusLabel});
 viewer=new ModelViewer(els['model-canvas'],{onCameraChange:()=>{if(compareViewer&&state.compare){compareViewer.camera={...viewer.camera};compareViewer.draw();}drawAxis();syncViewerState();},onError:showError});
 compareViewer=new ModelViewer(els['compare-canvas'],{onCameraChange:()=>{viewer.camera={...compareViewer.camera};viewer.draw();drawAxis();syncViewerState();},onError:showError});
 dsh=new NativeHarness({onError:notify,getTasks:()=>tasks,onDraft:showDraft,selectTask:showTask,onReconnect:loadTasks,onMeta:meta=>{mergeTask(meta);if(task?.id===meta.id)syncTaskContent().catch(e=>showError(e.message));},onResult:()=>syncTaskContent().catch(e=>showError(e.message))});
 emptyModel();await dsh.init();await loadTasks();
 }catch(error){els['loading-state'].hidden=true;els.workspace.setAttribute('aria-busy','false');showError(error.message);}}
init();
