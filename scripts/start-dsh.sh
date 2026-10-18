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
cleanup() { rm -f -- "$runtime_patch"; }
trap cleanup EXIT
adapter_path="$plugin_root/dsh/mandifuel-shell-env.mjs"
adapter_json="$(python3 -P -B -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$adapter_path")"
{
    printf '%s\n' '- insert:'
    printf '%s\n' '    - id: mandifuel-shell-environment'
    printf '      name: %s\n' "$adapter_json"
} >"$runtime_patch"

printf '%s\n' "DSH: $dsh_executable" "DSH mode: $mode" "Node.js: $MANDIFUEL_NODE"
if (( check_only )); then
    if [[ "$mode" == "web" ]]; then
        "$MANDIFUEL_NODE" "$dsh_executable" --profile web --patch "$patch_file" --patch "$runtime_patch" --patch "$web_patch_file" --dump-config >/dev/null
    else
        "$MANDIFUEL_NODE" "$dsh_executable" --profile headless --patch "$patch_file" --patch "$runtime_patch" --dump-config >/dev/null
    fi
    printf '%s\n' "MANDiFuel DSH startup check: PASS"
    exit 0
fi

# DSH owns the Web session's workspace; headless keeps the caller's directory.
if [[ "$mode" == "web" ]]; then
    "$MANDIFUEL_NODE" "$dsh_executable" web --patch "$patch_file" --patch "$runtime_patch" --patch "$web_patch_file" "$@"
    exit $?
fi
"$MANDIFUEL_NODE" "$dsh_executable" --profile headless --patch "$patch_file" --patch "$runtime_patch" "$@"
