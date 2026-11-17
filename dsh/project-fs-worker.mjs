// Invoked with this source captured at host startup, inside the kernel boundary.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const native=async name=>import(pathToFileURL(require.resolve('@deepseek-ai/'+name)));
const {Context}=await native('cordis');
const {LocalFileSystem}=await native('dsh-fs-local');
const ctx=new Context();
const fs=new LocalFileSystem(ctx,LocalFileSystem.Config({cwd:process.env.MANDIFUEL_PROJECT_ROOT}));
try {
  let input='';for await(const chunk of process.stdin) input+=chunk;
  const {operation,target,args}=JSON.parse(input);
  if (!['writeText','editText'].includes(operation)) throw new Error('unsupported file mutation');
  const result=await fs[operation](target,...args);
  process.stdout.write(JSON.stringify({result}));
} catch(error) {
  process.stdout.write(JSON.stringify({error:{message:error.message,code:error.code}}));
  process.exitCode=1;
}
