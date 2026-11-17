import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { checkedCwd } from './project-boundary.mjs';
const require=createRequire(process.env.MANDIFUEL_DSH_EXECUTABLE);
const {default:Policy}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-sandbox-policy')));

export default class ProjectPolicy extends Policy {
  resolve(request={}) {
    const policy=super.resolve(request);
    // Native tools also use workspaceRoot as the base for relative file paths
    // and command cwd. Preserve that session directory; grants are a separate
    // concern handled by ProjectSandbox and the hard subprocess boundary.
    return {...policy,mode:policy.mode==='read-only'?'read-only':'workspace-write',workspaceRoot:checkedCwd(policy.workspaceRoot)};
  }
}
