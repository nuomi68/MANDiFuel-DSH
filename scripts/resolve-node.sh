#!/usr/bin/env bash

# Resolve the runtime from an explicit setting or the DSH installation itself.
# Do not depend on login-shell PATH initialization for npm's env-node shebang.
mandifuel_resolve_node() {
    local dsh_executable="$1" candidate="${MANDIFUEL_NODE:-}" directory
    if [[ -n "$candidate" ]]; then
        if [[ "$candidate" != /* || ! -x "$candidate" || -d "$candidate" ]]; then
            printf '%s\n' "MANDiFuel startup: MANDIFUEL_NODE must name an absolute Node.js executable." >&2
            return 69
        fi
    else
        directory="$(dirname -- "$(readlink -f -- "$dsh_executable")")"
        while [[ "$directory" != / ]]; do
            if [[ -x "$directory/bin/node" && ! -d "$directory/bin/node" ]]; then
                candidate="$directory/bin/node"
                break
            fi
            directory="$(dirname -- "$directory")"
        done
        [[ -n "$candidate" ]] || candidate="$(command -v node || true)"
        if [[ "$candidate" != /* || ! -x "$candidate" || -d "$candidate" ]]; then
            printf '%s\n' "MANDiFuel startup: Node.js is unavailable; set MANDIFUEL_NODE to its absolute executable." >&2
            return 69
        fi
    fi
    candidate="$(readlink -f -- "$candidate")"
    if ! "$candidate" --version >/dev/null 2>&1; then
        printf '%s\n' "MANDiFuel startup: configured Node.js cannot execute." >&2
        return 69
    fi
    MANDIFUEL_NODE="$candidate"
    PATH="$(dirname -- "$candidate"):$PATH"
    export MANDIFUEL_NODE PATH
}
