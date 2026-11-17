import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {projectRoot} from './project-boundary.mjs';
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const {default:Sandbox}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-sandbox-local')));
export default class ProjectSandbox extends Sandbox {
  confine(argv,policy){
    return super.confine(argv,{...policy,mode:policy.mode==='read-only'?'read-only':'workspace-write',workspaceRoot:projectRoot});
  }
}
