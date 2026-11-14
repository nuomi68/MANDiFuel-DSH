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
  for (const id of ['tool-web','web-search-deepseek','web-fetch-http','subprocess']) {
    if (row(id).disabled!==true) throw new Error(`MANDiFuel offline configuration: ${id} must be disabled`);
  }
  const offline=row('mandifuel-offline-subprocess');
  if (offline.disabled===true || offline.name!==expectedAdapter)
    throw new Error('MANDiFuel offline configuration: required offline subprocess backend is not active');
  const expectedPersona=readFileSync(new URL('./run-assistant-persona.md',import.meta.url),'utf8');
  if (row('system-prompt').config?.persona!==expectedPersona)
    throw new Error('MANDiFuel configuration: run-assistant persona must be active');
  return { task_network:'offline', web_tools:false, subprocess_backend:offline.id };
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
  console.log('MANDiFuel offline configuration: PASS (run-assistant persona active; web tools off; task subprocess backend active)');
}
