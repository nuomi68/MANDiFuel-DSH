/** Keep native process management and filesystem confinement; add task-only offline execution. */
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const executable = process.env.MANDIFUEL_DSH_EXECUTABLE;
const python = process.env.MANDIFUEL_OFFLINE_PYTHON || process.env.MANDIFUEL_TASK_PYTHON;
if (!executable?.startsWith("/") || !python?.startsWith("/")) {
  throw new Error("MANDiFuel offline subprocess: launcher paths are unavailable");
}
const require = createRequire(executable);
const { LocalSubprocessRuntime } = await import(pathToFileURL(
  require.resolve("@deepseek-ai/dsh-subprocess-local")));
const launcher = fileURLToPath(new URL("./offline-exec.py", import.meta.url));

export default class OfflineSubprocessRuntime extends LocalSubprocessRuntime {
  offline(spec) {
    return { ...spec, argv: [python, "-I", "-B", launcher, "--", ...spec.argv] };
  }
  spawn(spec) { return super.spawn(this.offline(spec)); }
  spawnTerminal(spec) { return super.spawnTerminal(this.offline(spec)); }
}
