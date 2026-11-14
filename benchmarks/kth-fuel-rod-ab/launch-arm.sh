#!/usr/bin/env bash
set -euo pipefail
bench_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
plugin_root="$BENCH_PLUGIN_ROOT"
arm="$1"
source "$plugin_root/scripts/prepare-agent.sh"
mandifuel_prepare_agent_environment "$plugin_root"
source "$plugin_root/scripts/resolve-node.sh"
mandifuel_resolve_node "$MANDIFUEL_DSH"
task="$(cat "$bench_dir/task.txt")"
unset BENCH_PLUGIN_ROOT
if [[ "$arm" == bare ]]; then
    unset MANDIFUEL_PLUGIN_ROOT
    exec "$MANDIFUEL_NODE" "$(readlink -f -- "$MANDIFUEL_DSH")" --profile headless \
        --patch "$bench_dir/common.patch.yml" --patch "$bench_dir/bare.patch.yml" "$task"
elif [[ "$arm" == skill ]]; then
    exec bash "$plugin_root/scripts/start-dsh.sh" headless --patch "$bench_dir/common.patch.yml" "$task"
else
    exit 64
fi
