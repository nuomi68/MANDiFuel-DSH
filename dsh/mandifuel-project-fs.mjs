/** Native atomic file semantics, with every mutation in a confined child. */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { projectRoot, contains } from './project-boundary.mjs';
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const native=async name=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)));
const {LocalFileSystem}=await native('dsh-fs-local');
const {FsError}=await native('dsh-fs');
const launcher=readFileSync(new URL('./offline-exec.py',import.meta.url),'utf8');
const worker=readFileSync(new URL('./project-fs-worker.mjs',import.meta.url),'utf8');
const python=process.env.MANDIFUEL_TASK_PYTHON;
const executable=process.env.MANDIFUEL_DSH_EXECUTABLE;
const node=process.execPath;

export default class ProjectFileSystem extends LocalFileSystem {
  static inject=['sandboxPolicy'];
  get sandboxMode(){return this.ctx.sandboxPolicy.defaultMode;}
  async mutate(operation,target,args,signal,policy) {
    if ((policy??this.ctx.sandboxPolicy.resolve()).mode==='read-only')
      throw new FsError('MANDiFuel: file writes are disabled in read-only mode','FS_SANDBOX_DENIED');
    // Resolve the stable absolute target again; never change its base directory.
    const fresh=await this.resolve(this.processPath(target));
    if (!contains(projectRoot,this.processPath(fresh)))
      throw new FsError('MANDiFuel: file write is outside the project boundary','FS_SANDBOX_DENIED');
    return this.withLock(fresh.targetKey,()=>new Promise((resolve,reject)=>{
      signal?.throwIfAborted();
      const child=spawn(python,['-I','-B','-c',launcher,'--project-root',projectRoot,'--',node,'--input-type=module','-e',worker],{
        cwd:projectRoot,env:{...process.env,MANDIFUEL_DSH_EXECUTABLE:executable,MANDIFUEL_PROJECT_ROOT:projectRoot},
        stdio:['pipe','pipe','pipe'],signal});
      let output='',diagnostic='';
      child.stdout.setEncoding('utf8');child.stdout.on('data',chunk=>output+=chunk);
      child.stderr.setEncoding('utf8');child.stderr.on('data',chunk=>diagnostic=(diagnostic+chunk).slice(-4096));
      child.on('error',reject);child.stdin.on('error',()=>{});
      child.on('close',code=>{try{
        const reply=JSON.parse(output);
        if (reply.error) throw new FsError(reply.error.message,reply.error.code??'FS_SANDBOX_DENIED');
        if (code!==0) throw new Error('file worker failed');
        resolve(reply.result);
      }catch(error){reject(output?error:new FsError('MANDiFuel confined file worker failed: '+diagnostic,'FS_SANDBOX_DENIED'));}});
      child.stdin.end(JSON.stringify({operation,target:fresh,args}));
    }));
  }
  writeText(target,content,expected,signal,policy){return this.mutate('writeText',target,[content,expected],signal,policy);}
  editText(target,edit,expected,signal,policy){return this.mutate('editText',target,[edit,expected],signal,policy);}
}
