// Exercise the actual native subprocess + bash + filesystem sandbox services.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const executable=process.env.MANDIFUEL_DSH_EXECUTABLE;
assert.ok(executable && process.env.MANDIFUEL_TASK_PYTHON);
const require=createRequire(executable);
const native=async(name)=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)));
const {Context}=await native('cordis');
const {default:Sandbox}=await native('dsh-sandbox-local');
const {default:Policy}=await native('dsh-sandbox-policy');
const { SessionProjectionRegistry }=await native('dsh-session-projection');
const {default:Bash}=await native('dsh-bash-sandbox');
const {default:Offline}=await import('../../dsh/mandifuel-offline-subprocess.mjs');
const workspace=mkdtempSync(join(tmpdir(),'mandifuel-native-offline-workspace-'));
const outside=mkdtempSync(join(tmpdir(),'mandifuel-native-offline-outside-'));
const ctx=new Context();
const runtime=new Offline(ctx);
new SessionProjectionRegistry(ctx);
new Sandbox(ctx, Sandbox.Config({}));
new Policy(ctx,Policy.Config({mode:'workspace-write',workspaceRoot:workspace}));
const shell=new Bash(ctx,Bash.Config({timeoutMs:10000}));
const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";
const py=process.env.MANDIFUEL_TASK_PYTHON;
async function run(code, policy) {
 const spec=shell.resolve({command:`${quote(py)} -c ${quote(code)}`,workdir:workspace,
     ...(policy?{sandboxPolicy:policy}:{})});
 return shell.run(spec);
}
try {
 let result=await run("from pathlib import Path; Path('card.txt').write_text('local input'); print(6*7)");
 assert.equal(result.exitCode,0,result.stderr.text);
 assert.equal(result.stdout.text.trim(),'42');
 assert.equal(readFileSync(join(workspace,'card.txt'),'utf8'),'local input');
 result=await run('import socket; socket.socket(socket.AF_INET)');
 assert.notEqual(result.exitCode,0);
 assert.match(result.stderr.text,/Operation not permitted/);
 // Runtime mode escalation does not remove offline confinement.
 result=await run('import socket; socket.socket(socket.AF_INET6)',{mode:'danger-full-access',workspaceRoot:workspace});
 assert.notEqual(result.exitCode,0);
 assert.match(result.stderr.text,/Operation not permitted/);
 // Native read-only file policy still rejects writes, even within /tmp.
 result=await run(`from pathlib import Path; Path(${JSON.stringify(join(outside,'denied.txt'))}).write_text('x')`,
                  {mode:'read-only',workspaceRoot:workspace});
 assert.notEqual(result.exitCode,0);
 assert.match(result.stderr.text,/Permission denied|Read-only file system/i);
 const handle=shell.start(shell.resolve({command:`${quote(py)} -c 'import socket; socket.socket(socket.AF_INET)'`,workdir:workspace}));
 await handle.done;
 assert.notEqual(handle.exitCode,0);
 const terminal=await runtime.spawnTerminal({argv:[py,'-c','import socket; socket.socket(socket.AF_INET)'],
   cwd:workspace,rows:24,cols:80,graceMs:1000});
 let terminalText='';
 const drain=(async()=>{for await(const chunk of terminal.output) terminalText+=chunk.toString();})();
 const terminalOutcome=await terminal.done; await drain; await terminal.terminate();
 assert.notEqual(terminalOutcome.exitCode,0);
 assert.match(terminalText,/Operation not permitted/);
 // Host API transport remains possible: create and close a socket, never connect.
 const net=await import('node:net');
 const socket=new net.Socket(); socket.destroy();
 console.log('PASS: actual native foreground/background/terminal subprocesses offline; local task IO and native filesystem policy retained; full-access mode still offline');
} finally { rmSync(workspace,{recursive:true,force:true});rmSync(outside,{recursive:true,force:true}); }
