// Integration: real native services, including permissions, edits and PTY.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {mkdirSync,mkdtempSync,readFileSync,renameSync,rmSync,symlinkSync,unlinkSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const workspace=mkdtempSync(join(tmpdir(),'mandifuel-project-services-'));
const outside=mkdtempSync(join(tmpdir(),'mandifuel-project-services-outside-'));
process.env.MANDIFUEL_PROJECT_ROOT=workspace;
process.env.MANDIFUEL_DEFAULT_WORKDIR=workspace;
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const native=async name=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)));
const {Context}=await native('cordis');
const {assertSupportedJsonSchema}=await native('dsh-tools');
const {SCHEMA}=await import('../../frontend/native-plugin/presenter.mjs');
assertSupportedJsonSchema(SCHEMA);
const {SessionProjectionRegistry}=await native('dsh-session-projection');
const {default:Sandbox}=await import('../../dsh/mandifuel-project-sandbox.mjs');
const {default:Bash}=await native('dsh-bash-sandbox');
const {default:Policy}=await import('../../dsh/mandifuel-project-policy.mjs');
const {default:FileSystem}=await import('../../dsh/mandifuel-project-fs.mjs');
const {default:Runtime}=await import('../../dsh/mandifuel-offline-subprocess.mjs');
const ctx=new Context();
new SessionProjectionRegistry(ctx);
const policy=new Policy(ctx,Policy.Config({mode:'workspace-write',workspaceRoot:workspace}));
new Sandbox(ctx,Sandbox.Config({}));
const runtime=new Runtime(ctx);
const fs=new FileSystem(ctx,FileSystem.Config({cwd:workspace}));
const shell=new Bash(ctx,Bash.Config({timeoutMs:10000}));
const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";
const full={mode:'danger-full-access',workspaceRoot:'/'};
try {
  const protectedPath=join(outside,'protected');writeFileSync(protectedPath,'protected');
  symlinkSync(outside,join(workspace,'escape'));
  const target=await fs.resolve('card.txt');
  const created=await fs.writeText(target,'elastic=50', {kind:'createIfAbsent'});
  assert.equal(created.operation,'create');
  const edited=await fs.editText(target,{oldString:'50',newString:'81.25',replaceAll:false},{version:created.version});
  assert.equal(readFileSync(join(workspace,'card.txt'),'utf8'),'elastic=81.25');
  await assert.rejects(fs.editText(target,{oldString:'81.25',newString:'bad'}, {version:created.version}),/changed since|stale/i);
  assert.notEqual(edited.version,created.version);
  for(const path of [protectedPath,join(outside,'new'),join(workspace,'escape/protected'),join(workspace,'escape/new')]) {
    const dest=await fs.resolve(path);
    await assert.rejects(fs.writeText(dest,'bad',undefined,undefined,full),/outside the project/);
    await assert.rejects(fs.editText(dest,{oldString:'protected',newString:'bad'},undefined,undefined,full),/outside the project/);
  }
  await assert.rejects(fs.writeText(target,'bad',undefined,undefined,{mode:'read-only',workspaceRoot:workspace}),/read-only/);
  assert.equal(readFileSync(protectedPath,'utf8'),'protected');
  // Swap an ancestor after the host's canonical check. The worker's kernel
  // boundary must still stop the native atomic writer reaching the outside.
  const slot=join(workspace,'slot');mkdirSync(slot);
  const raced=await fs.resolve(join(slot,'protected'));
  const withLock=fs.withLock.bind(fs);
  fs.withLock=async(key,operation)=>{
    renameSync(slot,slot+'-original');symlinkSync(outside,slot);
    try{return await withLock(key,operation);}
    finally{unlinkSync(slot);renameSync(slot+'-original',slot);}
  };
  await assert.rejects(fs.writeText(raced,'bad'),/denied|EACCES/i);
  fs.withLock=withLock;
  assert.equal(readFileSync(protectedPath,'utf8'),'protected');
  assert.deepEqual(policy.resolve({mode:'danger-full-access'}),{mode:'workspace-write',workspaceRoot:workspace});
  assert.equal(policy.resolve({mode:'read-only'}).mode,'read-only');
  assert.throws(()=>policy.resolve({session:{id:'fake',header:{cwd:outside}},mode:'workspace-write'}),/outside/);
  const sessionDir=join(workspace,'task','workspace');mkdirSync(sessionDir,{recursive:true});
  const resolved=policy.resolve({session:{id:'fake',header:{cwd:sessionDir}},mode:'workspace-write'});
  assert.equal(resolved.workspaceRoot,sessionDir,'project write grants must not replace the session cwd');
  const relative=await fs.resolve('relative.txt',{cwd:resolved.workspaceRoot});
  await fs.writeText(relative,'session-local');
  assert.equal(readFileSync(join(sessionDir,'relative.txt'),'utf8'),'session-local');
  const py=process.env.MANDIFUEL_TASK_PYTHON;
  const sibling=join(workspace,'shared.txt');
  const wide=shell.resolve({command:`${quote(py)} -c ${quote(`from pathlib import Path; assert Path.cwd()==Path(${JSON.stringify(sessionDir)}); Path(${JSON.stringify(sibling)}).write_text('whole project')`)}`,workdir:resolved.workspaceRoot,sandboxPolicy:resolved});
  const written=await shell.run(wide);assert.equal(written.exitCode,0,written.stderr.text);
  assert.equal(readFileSync(sibling,'utf8'),'whole project');
  const spec=shell.resolve({command:`${quote(py)} -c ${quote(`from pathlib import Path; Path(${JSON.stringify(protectedPath)}).write_text('bad')`)}`,workdir:workspace,sandboxPolicy:full});
  const denied=await shell.run(spec);
  assert.notEqual(denied.exitCode,0);assert.match(denied.stderr.text,/Permission denied/);
  assert.throws(()=>runtime.spawn({argv:[py,'-c','print(1)'],cwd:outside}),/outside/);
  const terminal=await runtime.spawnTerminal({argv:[py,'-c',`from pathlib import Path; Path(${JSON.stringify(protectedPath)}).write_text('bad')`],cwd:workspace,rows:24,cols:80,graceMs:1000});
  let text='';const drain=(async()=>{for await(const chunk of terminal.output)text+=chunk;})();
  const outcome=await terminal.done;await drain;await terminal.terminate();
  assert.notEqual(outcome.exitCode,0);assert.match(text,/Permission denied/);
  console.log('PASS: native file create/edit/version guards; outside and symlink writes denied even with full access; read-only preserved; shell and PTY confined; cwd and policy cannot widen project');
} finally {
  await runtime.disposeManagedProcesses();
  rmSync(workspace,{recursive:true,force:true});rmSync(outside,{recursive:true,force:true});
}
