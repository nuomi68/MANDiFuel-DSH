import { realpathSync, statSync } from 'node:fs';
import { dirname, isAbsolute, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export function contains(root, path) {
  const suffix=relative(root,path);
  return suffix==='' || (!isAbsolute(suffix) && suffix!=='..' && !suffix.startsWith('..'+sep));
}
// Captured from the trusted launch environment once, never a tool argument.
export const projectRoot=realpathSync(process.env.MANDIFUEL_PROJECT_ROOT || dirname(dirname(fileURLToPath(import.meta.url))));
if (projectRoot==='/' || !statSync(projectRoot).isDirectory()) throw new Error('MANDiFuel: invalid project root');
export function checkedCwd(cwd=process.env.MANDIFUEL_DEFAULT_WORKDIR || projectRoot) {
  const path=realpathSync(cwd);
  if (!contains(projectRoot,path)) throw new Error('MANDiFuel: working directory is outside the project write boundary');
  return path;
}
