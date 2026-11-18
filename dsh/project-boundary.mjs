import { realpathSync, statSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export function contains(root, path) {
  const suffix=relative(root,path);
  return suffix==='' || (!isAbsolute(suffix) && suffix!=='..' && !suffix.startsWith('..'+sep));
}
// Captured from the trusted launch environment once, never a tool argument.
export const projectRoot=realpathSync(process.env.MANDIFUEL_PROJECT_ROOT || dirname(dirname(fileURLToPath(import.meta.url))));
if (projectRoot==='/' || !statSync(projectRoot).isDirectory()) throw new Error('MANDiFuel: invalid project root');
// The operator pins the physical runs directory. A symlink alone never grants access.
function configuredRunsRoot(path) {
  if (!path) return null;
  if (!isAbsolute(path) || path !== realpathSync(path) || !statSync(path).isDirectory() ||
      contains(path, projectRoot) || realpathSync(join(projectRoot, 'runs')) !== path) {
    throw new Error('MANDiFuel: configured runs root must be the canonical target of project/runs');
  }
  return contains(projectRoot, path) ? null : path;
}
export const runsRoot=configuredRunsRoot(process.env.MANDIFUEL_RUNS_ROOT);
export const launcherRootArgs=Object.freeze(['--project-root',projectRoot,...(runsRoot?['--runs-root',runsRoot]:[])]);
export function writablePath(path) {
  return contains(projectRoot,path) || (runsRoot !== null && contains(runsRoot,path));
}
export function checkedCwd(cwd=process.env.MANDIFUEL_DEFAULT_WORKDIR || projectRoot) {
  const path=realpathSync(cwd);
  if (!writablePath(path)) throw new Error('MANDiFuel: working directory is outside the project write boundary');
  return path;
}
