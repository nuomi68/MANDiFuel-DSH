#!/usr/bin/env bash
set -euo pipefail

plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$plugin_root/scripts/prepare-agent.sh"

check_only=0
if [[ "${1:-}" == "--check" ]]; then
    check_only=1
    shift
fi

mode="${1:-web}"
case "$mode" in
    web|headless)
        (($#)) && shift
        ;;
    *)
        printf '%s\n' "Usage: $0 [--check] [web|headless] [DSH arguments...]" >&2
        exit 64
        ;;
esac

mandifuel_prepare_agent_environment "$plugin_root"

protocol_file="$plugin_root/STUDY_PROTOCOL.md"
if [[ ! -r "$protocol_file" || ! -s "$protocol_file" ]]; then
    printf '%s\n' "MANDiFuel startup: Study protocol is unavailable or empty: $protocol_file" >&2
    exit 69
fi
dsh_executable="${MANDIFUEL_DSH:-}"
if [[ -z "$dsh_executable" ]]; then
    dsh_executable="$(command -v dsh || true)"
fi
if [[ -z "$dsh_executable" || "$dsh_executable" != /* || ! -x "$dsh_executable" ]]; then
    printf '%s\n' "MANDiFuel startup: set MANDIFUEL_DSH to the absolute DSH executable." >&2
    exit 69
fi
dsh_executable="$(readlink -f -- "$dsh_executable")"
export MANDIFUEL_DSH_EXECUTABLE="$dsh_executable"
# shellcheck disable=SC1091
source "$plugin_root/scripts/resolve-node.sh"
mandifuel_resolve_node "$dsh_executable"
patch_file="$plugin_root/dsh/cordis.patch.yml"
if [[ ! -r "$patch_file" ]]; then
    printf '%s\n' "MANDiFuel startup: DSH configuration patch is unavailable: $patch_file" >&2
    exit 69
fi
web_patch_file="$plugin_root/dsh/web-default.patch.yml"
if [[ "$mode" == "web" && ! -r "$web_patch_file" ]]; then
    printf '%s\n' "MANDiFuel startup: DSH Web preset patch is unavailable: $web_patch_file" >&2
    exit 69
fi

# DSH resolves custom plugin specifiers from its machine-local profile rather
# than from the overlay file. Generate a process-local overlay with the already
# resolved adapter path. The adapter reads STUDY_PROTOCOL.md from its plugin
# root; the overlay contains no protocol text or credentials and is removed on exit.
runtime_patch="$(mktemp "${TMPDIR:-/tmp}/mandifuel-dsh-patch-XXXXXX.yml")"
runtime_config="$(mktemp "${TMPDIR:-/tmp}/mandifuel-dsh-config-XXXXXX.yml")"
cleanup() { rm -f -- "$runtime_patch" "$runtime_config"; }
trap cleanup EXIT
adapter_path="$plugin_root/dsh/mandifuel-shell-env.mjs"
offline_adapter_path="$plugin_root/dsh/mandifuel-offline-subprocess.mjs"
project_fs_path="$plugin_root/dsh/mandifuel-project-fs.mjs"
project_policy_path="$plugin_root/dsh/mandifuel-project-policy.mjs"
project_sandbox_path="$plugin_root/dsh/mandifuel-project-sandbox.mjs"
persona_file="$plugin_root/dsh/run-assistant-persona.md"
if [[ ! -r "$persona_file" || ! -s "$persona_file" ]]; then
    printf '%s\n' "MANDiFuel startup: run-assistant persona is unavailable: $persona_file" >&2
    exit 69
fi
persona_json="$(python3 -P -B -c 'import json, pathlib, sys; print(json.dumps(pathlib.Path(sys.argv[1]).read_text()))' "$persona_file")"
offline_adapter_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$offline_adapter_path")"
project_fs_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$project_fs_path")"
project_policy_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$project_policy_path")"
project_sandbox_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$project_sandbox_path")"
# Probe the same fail-closed launcher used for task children; no solver/network call.
(cd -- "$MANDIFUEL_DEFAULT_WORKDIR"; "$MANDIFUEL_TASK_PYTHON" -I -B "$plugin_root/dsh/offline-exec.py" --project-root "$MANDIFUEL_PROJECT_ROOT" -- true)
adapter_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$adapter_path")"

{
    printf '%s\n' '- id: system-prompt'
    printf '%s\n' '  config:'
    printf '    persona: %s\n' "$persona_json"
    printf '%s\n' '- id: subprocess'
    printf '%s\n' '  disabled: true'
    printf '%s\n' '- id: fs-sandbox'
    printf '%s\n' '  disabled: true'
    printf '%s\n' '- id: sandbox-policy'
    printf '%s\n' '  disabled: true'
    printf '%s\n' '- id: sandbox'
    printf '%s\n' '  disabled: true'
    printf '%s\n' '- insert:'
    printf '%s\n' '    - id: mandifuel-project-sandbox'
    printf '      name: %s\n' "$project_sandbox_json"
    printf '%s\n' '    - id: mandifuel-project-policy'
    printf '      name: %s\n' "$project_policy_json"
    printf '%s\n' '      config:' '        mode: workspace-write' '        workspaceRoot: !!js process.env.MANDIFUEL_PROJECT_ROOT'
    printf '%s\n' '    - id: mandifuel-project-fs'
    printf '      name: %s\n' "$project_fs_json"
    printf '%s\n' '    - id: mandifuel-offline-subprocess'
    printf '      name: %s\n' "$offline_adapter_json"
    printf '%s\n' '    - id: mandifuel-shell-environment'
    printf '      name: %s\n' "$adapter_json"
} >"$runtime_patch"

printf '%s\n' "DSH: $dsh_executable" "DSH mode: $mode" "Node.js: $MANDIFUEL_NODE"
# Include caller-supplied overlays in the check; --help or task text must not
# replace the config dump. Do not print the dump (it can contain local settings).
validation_patches=()
expect_patch=0
for argument in "$@"; do
    if (( expect_patch )); then
        validation_patches+=(--patch "$argument")
        expect_patch=0
    elif [[ "$argument" == --patch ]]; then
        expect_patch=1
    elif [[ "$argument" == --patch=* ]]; then
        validation_patches+=("$argument")
    fi
done
# Validate the applied composition on every launch. Native patches can be
# skipped with only a warning; refuse that state before exposing task tools.
if [[ "$mode" == "web" ]]; then
    "$MANDIFUEL_NODE" "$dsh_executable" --profile web --patch "$patch_file" --patch "$runtime_patch" --patch "$web_patch_file" "${validation_patches[@]}" --dump-config >"$runtime_config"
else
    "$MANDIFUEL_NODE" "$dsh_executable" --profile headless --patch "$patch_file" --patch "$runtime_patch" "${validation_patches[@]}" --dump-config >"$runtime_config"
fi
"$MANDIFUEL_NODE" "$plugin_root/dsh/check-offline-config.mjs" "$runtime_config" "$offline_adapter_path"
if (( check_only )); then
    printf '%s\n' "MANDiFuel DSH startup check: PASS"
    exit 0
fi

# Web sessions keep their task directory. New standalone sessions start in the
# configured default; existing headless callers inside the project keep cwd.
if [[ "$mode" == web ]]; then
    cd -- "$MANDIFUEL_DEFAULT_WORKDIR"
else
    case "$PWD/" in "$MANDIFUEL_PROJECT_ROOT/"*) ;; *) cd -- "$MANDIFUEL_DEFAULT_WORKDIR";; esac
fi
if [[ "$mode" == "web" ]]; then
    "$MANDIFUEL_NODE" "$dsh_executable" web --patch "$patch_file" --patch "$runtime_patch" --patch "$web_patch_file" "$@"
    exit $?
fi
"$MANDIFUEL_NODE" "$dsh_executable" --profile headless --patch "$patch_file" --patch "$runtime_patch" "$@"
