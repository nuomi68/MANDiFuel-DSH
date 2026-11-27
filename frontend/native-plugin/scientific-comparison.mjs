import {CHART_TYPES} from '../assets/chart-view.js';
import {hasWorkspaceContent} from '../assets/ui-placement.js';

// Only a completed research result needs this review. A later styling request
// edits the existing page without imposing another analysis layout.
export function comparisonReview(facts){
 if(facts.task.status!=='completed'||facts.task.displayOnly)return null;
 const history=(facts.workspaceHistory||[]).filter(h=>Object.keys(h.comparableResponses||{}).length);
 const study=facts.study?.counts?.completed>=2&&facts.studyVariables?.responses?.length;
 const tables=(facts.availableTables||[]).filter(t=>t.rows>=2);
 const completedTables=tables.filter(t=>t.hasCaseComparison);
 if(!study&&!history.length&&!completedTables.length)return null;
 const records=(facts.availableRecords||[]).filter(r=>r.count>=2);
 const files=new Set((study||history.length?[...tables,...records,...history]:completedTables).map(r=>r.file));
 const ui=facts.presentation?.ui;
 const inputs=new Set((facts.studyVariables?.parameters||[]).map(p=>p.id));
 const responses=new Set((facts.studyVariables?.responses||[]).map(r=>r.id));
 for(const h of history){
  for(const row of h.samples||[])for(const key of Object.keys(row.point||{}))inputs.add(key);
  for(const path of Object.keys(h.comparableResponses))responses.add(path.split('.').at(-1));
 }
 function onlyDesignInputs(dataset,axes){
  // Reject a known input design plotted against itself. Other result files
  // may use physical names or units that differ from the Study response IDs.
  const paths=axes.map(key=>dataset.columns?.find(c=>c.id===key)?.path||key);
  return paths.length>0&&paths.every(path=>path.startsWith('point.')||inputs.has(path)&&!responses.has(path));
 }
 const charts=[];
 function visit(node){
  if(!node)return;
  if(CHART_TYPES.has(node.type)){
   const series=node.source?[node]:node.series||[];
   const views=new Set();let measured=false;
   for(const s of series){
    const source=s.source;
    if(!source)continue;
    const axes=['x','y','xLow','xHigh','yLow','yHigh','value'].map(key=>s[key]).filter(Boolean);
    if(source.kind==='study'){
     if(source.select!=='best'&&axes.some(key=>key.startsWith('response.')||key.startsWith('best.')))measured=true;
     continue;
    }
    if(source.kind==='dataset'){
     const dataset=ui.datasets?.[source.dataset];
     if(!dataset||onlyDesignInputs(dataset,axes))continue;
     if(files.has(dataset.file))measured=true;
    }
    const view=source.view||source.selection?.view;
    if(view)views.add(view);
   }
   if(views.size>=2||measured)charts.push(node.id);
  }
  for(const child of node.children||[])visit(child);
 }
 visit(ui?.root);visit(ui?.aside);
 const nativeOverview=Boolean(study&&(ui?.scope==='model'||ui?.mode!=='replace'||!hasWorkspaceContent(ui.root)));
 return {kind:facts.study?.kind||'multi-case',histories:history.map(h=>h.file),tables:tables.map(t=>t.file),charts,nativeOverview};
}

export function missingComparison(review,exception,request){
 if(!review||review.nativeOverview||review.charts.length)return false;
 const reason=exception?.reason?.trim();
 if(!reason||reason.length>240)return true;
 if(exception.kind==='requested-format')return !request?.includes(reason);
 return exception.kind!=='incomparable-data';
}
