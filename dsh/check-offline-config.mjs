/** Verify composed native rows, so skipped overlays cannot silently enable network tools. */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

export function verifyOfflineRows(document, expectedAdapter) {
  const rows=[];
  function visit(value) {
    if (Array.isArray(value)) { for (const item of value) visit(item); }
    else if (value && typeof value==='object') {
      if (typeof value.id==='string') rows.push(value);
      for (const child of Object.values(value)) visit(child);
    }
  }
  visit(document);
  function row(id) {
    const matches=rows.filter(item=>item.id===id);
    if (matches.length!==1) throw new Error(`MANDiFuel offline configuration: expected exactly one ${id} row`);
    return matches[0];
  }
  for (const id of ['tool-web','web-search-deepseek','web-fetch-http','subprocess','fs-sandbox','sandbox-policy','sandbox']) {
    if (row(id).disabled!==true) throw new Error(`MANDiFuel offline configuration: ${id} must be disabled`);
  }
  const offline=row('mandifuel-offline-subprocess');
  if (offline.disabled===true || offline.name!==expectedAdapter)
    throw new Error('MANDiFuel offline configuration: required offline subprocess backend is not active');
  for (const [id,file] of [['mandifuel-project-fs','mandifuel-project-fs.mjs'],['mandifuel-project-policy','mandifuel-project-policy.mjs'],['mandifuel-project-sandbox','mandifuel-project-sandbox.mjs']]) {
    const required=row(id);
    if(required.disabled===true || required.name!==new URL(file,import.meta.url).pathname)
      throw new Error(`MANDiFuel configuration: required project boundary ${id} is not active`);
  }
  const retrieval=row('mandifuel-retrieval');
  if (retrieval.disabled===true || retrieval.name!==new URL('./mandifuel-retrieval.mjs',import.meta.url).pathname)
    throw new Error('MANDiFuel configuration: retrieval host must be active');
  const expectedPersona=readFileSync(new URL('./run-assistant-persona.md',import.meta.url),'utf8');
  if (row('system-prompt').config?.persona!==expectedPersona)
    throw new Error('MANDiFuel configuration: run-assistant persona must be active');
  return { task_network:'offline', web_tools:false, subprocess_backend:offline.id,project_write_boundary:true };
}

if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
  const { parseDocument }=require('yaml');
  // Dump retains !!js configuration expressions. Preserve them as strings;
  // this validator never evaluates expressions or accesses credential values.
  const document=parseDocument(readFileSync(process.argv[2],'utf8'),{
    customTags:[{tag:'tag:yaml.org,2002:js',resolve:value=>value}],
  });
  if (document.errors.length) throw new Error('MANDiFuel offline configuration: cannot parse native dump');
  verifyOfflineRows(document.toJS(),process.argv[3]);
  console.log('MANDiFuel offline configuration: PASS (persona, retrieval host, offline subprocess and project policy active)');
}
