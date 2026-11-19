// Verify rendered native prompts, including a scoped Web-preset persona shadow.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { apply } from '../../dsh/mandifuel-shell-env.mjs';

const executable=process.env.MANDIFUEL_DSH_EXECUTABLE || '/home/lwz/.nvm/versions/node/v22.23.2/lib/node_modules/@deepseek-ai/dsh/lib/bin.js';
const require=createRequire(executable);
const native=async(name)=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)));
const {Context}=await native('cordis');
const {SystemPrompt,renderPrompt}=await native('dsh-system-prompt');
const {ShellEnvRegistry}=await native('dsh-shell-env');
const {createScope}=await native('dsh-scope');
const ctx=new Context();
const globalCoding='You are a coding agent. This is the global headless persona.';
const scopedCoding='You are a coding agent. This persona comes from the standard preset.';
const prompt=new SystemPrompt(ctx,SystemPrompt.Config({includeHarnessIdentity:false,persona:globalCoding}));
new ShellEnvRegistry(ctx,{dshHome:'/tmp/mandifuel-persona-check'});
prompt.tools(()=>({schemas:[{name:'local_contract',description:'Local tool',parameters:{type:'object',properties:{}}}]}));
const key={};const scoped=createScope(ctx,key);
scoped.ctx.systemPrompt.section({name:'deployment:persona',order:0,text:scopedCoding});
const globalBefore=await prompt.assemble();const scopedBefore=await prompt.assemble({scope:key});
assert.equal(renderPrompt(globalBefore),globalCoding);
assert.equal(renderPrompt(scopedBefore),scopedCoding);
apply(ctx);
const expected=readFileSync(new URL('../../dsh/run-assistant-persona.md',import.meta.url),'utf8');
for (const context of [{},{scope:key}]) {
  const assembly=await prompt.assemble(context);
  const personas=assembly.sections.filter(s=>s.name==='deployment:persona');
  assert.equal(personas.length,1);
  assert.equal(personas[0].text,expected);
  const rendered=renderPrompt(assembly);
  assert.ok(rendered.includes(expected));
  assert.ok(!rendered.includes(globalCoding) && !rendered.includes(scopedCoding));
  assert.deepEqual(assembly.tools,globalBefore.tools);
}
await scoped.dispose();
console.log('PASS: actual native global and scoped preset coding personas replaced by run-assistant identity; public tools retained');
