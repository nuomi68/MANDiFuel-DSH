import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {projectRoot,runsRoot} from './project-boundary.mjs';
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const {default:Sandbox}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-sandbox-local')));
export default class ProjectSandbox extends Sandbox {
  confine(argv,policy){
    const mode=policy.mode==='read-only'?'read-only':'workspace-write';
    const wrapped=super.confine(argv,{...policy,mode,workspaceRoot:projectRoot});
    if (!runsRoot || mode==='read-only') return wrapped;
    // DSH's Linux providers end the mount/grant profile with -- and the original command.
    const end=wrapped.argv.length-argv.length-1;
    const profile=wrapped.argv.slice(0,end);
    if (wrapped.argv[end]!=='--') throw new Error('Unrecognized DSH sandbox profile');
    if (profile.includes('--ro-bind')) profile.push('--bind',runsRoot,runsRoot);
    else if (profile.includes('--rw')) profile.push('--rw',runsRoot);
    else throw new Error('DSH sandbox cannot grant the configured runs directory');
    return {...wrapped,argv:[...profile,'--',...argv]};
  }
}
