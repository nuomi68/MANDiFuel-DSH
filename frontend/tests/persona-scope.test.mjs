import test from 'node:test';
import assert from 'node:assert/strict';
import {copyFile, mkdir, mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {apply} from '../../dsh/mandifuel-shell-env.mjs';
test('solver persona replaces interactive defaults and preserves private presentation roles',async()=>{
 const hooks={};apply({on:(name,fn)=>hooks[name]=fn,systemPrompt:{section(){}},shellEnv:{register(){}}});
 const original={sections:[{name:'deployment:persona',text:'private UI role'}]};
 const privateResult=await hooks['system-prompt/assemble'](original,{agent:{session:{header:{origin:'subagent'}}}},async()=>original);
 assert.equal(privateResult.sections[0].text,'private UI role');
 const main=await hooks['system-prompt/assemble'](original,{agent:{session:{header:{origin:'interactive'}}}},async()=>original);
 assert.match(main.sections[0].text,/OFFBEAT 计算运行助手/);
});

test('a long-lived host reads the current role at the next main prompt assembly',async(t)=>{
 const root=await mkdtemp(join(tmpdir(),'mandifuel-role-'));
 t.after(()=>rm(root,{recursive:true,force:true}));
 const dir=join(root,'dsh'),role=join(dir,'run-assistant-persona.md');
 await mkdir(dir);
 await copyFile(new URL('../../dsh/mandifuel-shell-env.mjs',import.meta.url),join(dir,'adapter.mjs'));
 await writeFile(join(root,'STUDY_PROTOCOL.md'),'protocol');
 await writeFile(role,'old role');
 const {apply}=await import(pathToFileURL(join(dir,'adapter.mjs')));
 const hooks={};
 apply({on:(name,fn)=>hooks[name]=fn,systemPrompt:{section(){}},shellEnv:{register(){}}});
 const next=async()=>({sections:[{name:'deployment:persona',text:'preset'}]});
 const assemble=async()=> (await hooks['system-prompt/assemble'](null,{},next)).sections[0].text;
 assert.equal(await assemble(),'old role');
 await writeFile(role,'updated role');
 assert.equal(await assemble(),'updated role');
});

test('a new private operator loads the current role in a long-lived host',async t=>{
 const root=await mkdtemp(join(tmpdir(),'mandifuel-ui-role-'));
 t.after(()=>rm(root,{recursive:true,force:true}));
 await mkdir(join(root,'agent'));await mkdir(join(root,'native-plugin'));
 const module=join(root,'native-plugin','frontend-agent.mjs'),role=join(root,'agent','ROLE.md');
 await copyFile(new URL('../native-plugin/frontend-agent.mjs',import.meta.url),module);
 const {readFrontendRole}=await import(pathToFileURL(module));
 await writeFile(role,'previous UI instructions');assert.equal(readFrontendRole(),'previous UI instructions');
 await writeFile(role,'current UI instructions');assert.equal(readFrontendRole(),'current UI instructions');
});
