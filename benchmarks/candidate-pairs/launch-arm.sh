#!/usr/bin/env bash
set -euo pipefail
bench_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
plugin_root="$BENCH_PLUGIN_ROOT"
prompt_file="$BENCH_PROMPT_FILE"
arm="$1"
source "$plugin_root/scripts/prepare-agent.sh"
mandifuel_prepare_agent_environment "$plugin_root"
source "$plugin_root/scripts/resolve-node.sh"
mandifuel_resolve_node "$MANDIFUEL_DSH"
task="$(cat "$prompt_file")"
unset BENCH_PLUGIN_ROOT BENCH_PROMPT_FILE
if [[ "${BENCH_PREFLIGHT_ONLY:-0}" == 1 ]]; then
    extra=(--dump-config)
elif [[ "${BENCH_PREFLIGHT_ONLY:-0}" == boot ]]; then
    extra=(--help)
else
    extra=("$task")
fi
if [[ "${BENCH_TOOLCHAIN_ONLY:-0}" == 1 ]]; then
    exec python3 -B "$bench_dir/isolate-launch.py" "$BENCH_ISOLATION_POLICY" -- \
        python3 -I -B "$bench_dir/offline-exec.py" -- python3 -B "$bench_dir/preflight_toolchain.py"
fi
if [[ "$arm" == bare ]]; then
    export MANDIFUEL_DSH_EXECUTABLE="$(readlink -f -- "$MANDIFUEL_DSH")"
    export MANDIFUEL_OFFLINE_PYTHON="$MANDIFUEL_TASK_PYTHON"
    offline_patch="$bench_dir/offline.patch.yml"
    python3 - "$bench_dir/mandifuel-offline-subprocess.mjs" "$offline_patch" <<'PYCFG'
import json,sys
from pathlib import Path
Path(sys.argv[2]).write_text('- id: subprocess\n  disabled: true\n- insert:\n    - id: mandifuel-offline-subprocess\n      name: '+json.dumps(sys.argv[1])+'\n')
PYCFG
    unset MANDIFUEL_PLUGIN_ROOT MANDIFUEL_ENVIRONMENT_READY MANDIFUEL_TASK_PYTHON MANDIFUEL_OFFBEAT_EXECUTABLE
    exec python3 -B "$bench_dir/isolate-launch.py" "$BENCH_ISOLATION_POLICY" -- \
        "$MANDIFUEL_NODE" "$(readlink -f -- "$MANDIFUEL_DSH")" --profile headless \
        --patch "$bench_dir/common.patch.yml" --patch "$bench_dir/bare.patch.yml" --patch "$offline_patch" "${extra[@]}"
elif [[ "$arm" == skill ]]; then
    exec python3 -B "$bench_dir/isolate-launch.py" "$BENCH_ISOLATION_POLICY" -- \
        bash "$plugin_root/scripts/start-dsh.sh" headless --patch "$bench_dir/common.patch.yml" "${extra[@]}"
else
    exit 64
fi
