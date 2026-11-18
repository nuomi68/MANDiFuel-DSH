#!/usr/bin/env bash
set -euo pipefail
runtime_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
plugin_root="$BENCH_PLUGIN_ROOT"
arm="$1"
task="$(cat "$BENCH_PROMPT_FILE")"
source "$plugin_root/scripts/prepare-agent.sh"
mandifuel_prepare_agent_environment "$plugin_root"
source "$plugin_root/scripts/resolve-node.sh"
mandifuel_resolve_node "$MANDIFUEL_DSH"
export MANDIFUEL_DSH_EXECUTABLE="$(readlink -f -- "$MANDIFUEL_DSH")"
export MANDIFUEL_OFFLINE_PYTHON="$MANDIFUEL_TASK_PYTHON"
unset BENCH_PLUGIN_ROOT BENCH_PROMPT_FILE
if [[ "${BENCH_PREFLIGHT_ONLY:-0}" == 1 ]]; then
    extra=(--dump-config)
else
    extra=("$task")
fi
if [[ "$arm" == skill ]]; then
    exec python3 -B "$runtime_dir/isolate-launch.py" "$BENCH_ISOLATION_POLICY" -- \
        bash "$plugin_root/scripts/start-dsh.sh" headless --patch "$runtime_dir/common.patch.yml" "${extra[@]}"
else
    unset MANDIFUEL_PLUGIN_ROOT MANDIFUEL_ENVIRONMENT_READY
    exec python3 -B "$runtime_dir/isolate-launch.py" "$BENCH_ISOLATION_POLICY" -- \
        "$MANDIFUEL_NODE" "$MANDIFUEL_DSH_EXECUTABLE" --profile headless \
        --patch "$runtime_dir/bare-runtime.patch.yml" --patch "$runtime_dir/common.patch.yml" "${extra[@]}"
fi
