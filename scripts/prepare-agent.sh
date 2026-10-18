#!/usr/bin/env bash

mandifuel_prepare_agent_environment() {
    local plugin_root="$1"
    local launcher_config="$plugin_root/configs/launcher.env"
    local openfoam_bashrc base_python base_python_dir task_python command_name version
    local caller_directory="$PWD"
    local mapping_key_name embedding_key_name rag_provider_status
    local -a available_study_libraries=() missing_study_libraries=()

    if [[ "$plugin_root" != /* || ! -d "$plugin_root/skills" || ! -f "$plugin_root/rag/query.py" ]]; then
        printf '%s\n' "MANDiFuel startup: plugin root is incomplete." >&2
        return 69
    fi
    if [[ -e "$plugin_root/configs/local.toml" || -e "$plugin_root/.mandifuel-runtime" ]]; then
        printf '%s\n' \
            "MANDiFuel startup: obsolete catalog or private Runtime data exists inside the plugin root." \
            "Remove configs/local.toml and .mandifuel-runtime; current Skills use rag/query.py and the configured case-library root." >&2
        return 78
    fi
    export MANDIFUEL_PLUGIN_ROOT="$plugin_root"
    if [[ ! -r "$launcher_config" ]]; then
        printf '%s\n' \
            "MANDiFuel startup: environment configuration is unavailable." \
            "Copy configs/launcher.env.example to configs/launcher.env and edit paths; see README.md." >&2
        return 78
    fi
    # Explicit per-process settings take precedence over machine-local defaults.
    # This keeps simultaneous DSH tasks and their retrieval caches isolated.
    local name
    local -A overrides=()
    local -a override_names=(
        MANDIFUEL_OPENFOAM_BASHRC MANDIFUEL_OFFBEAT_BIN MANDIFUEL_BASE_PYTHON
        MANDIFUEL_DSH MANDIFUEL_NODE MANDIFUEL_CASE_LIBRARY_ROOT
        MANDIFUEL_RAG_MAPPING_BASE_URL MANDIFUEL_RAG_MAPPING_MODEL
        MANDIFUEL_RAG_MAPPING_API_KEY_ENV MANDIFUEL_RAG_EMBEDDING_BASE_URL
        MANDIFUEL_RAG_EMBEDDING_MODEL MANDIFUEL_RAG_EMBEDDING_DIMENSION
        MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV MANDIFUEL_RAG_CACHE_DIR
        MANDIFUEL_RAG_TIMEOUT_SECONDS
    )
    for name in "${override_names[@]}"; do
        [[ -v "$name" ]] && overrides["$name"]="${!name}"
    done
    # shellcheck disable=SC1090
    source "$launcher_config"
    for name in "${!overrides[@]}"; do
        printf -v "$name" '%s' "${overrides[$name]}"
        export "$name"
    done
    openfoam_bashrc="${MANDIFUEL_OPENFOAM_BASHRC:-}"
    base_python="${MANDIFUEL_BASE_PYTHON:-}"
    MANDIFUEL_RAG_MAPPING_BASE_URL="${MANDIFUEL_RAG_MAPPING_BASE_URL:-https://api.deepseek.com}"
    MANDIFUEL_RAG_MAPPING_MODEL="${MANDIFUEL_RAG_MAPPING_MODEL:-deepseek-chat}"
    MANDIFUEL_RAG_MAPPING_API_KEY_ENV="${MANDIFUEL_RAG_MAPPING_API_KEY_ENV:-DEEPSEEK_API_KEY}"
    MANDIFUEL_RAG_EMBEDDING_BASE_URL="${MANDIFUEL_RAG_EMBEDDING_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
    MANDIFUEL_RAG_EMBEDDING_MODEL="${MANDIFUEL_RAG_EMBEDDING_MODEL:-text-embedding-v3}"
    MANDIFUEL_RAG_EMBEDDING_DIMENSION="${MANDIFUEL_RAG_EMBEDDING_DIMENSION:-1024}"
    MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV="${MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV:-DASHSCOPE_API_KEY}"
    MANDIFUEL_RAG_TIMEOUT_SECONDS="${MANDIFUEL_RAG_TIMEOUT_SECONDS:-120}"
    if [[ "$openfoam_bashrc" != /* || ! -r "$openfoam_bashrc" ]]; then
        printf '%s\n' "MANDiFuel startup: OpenFOAM bashrc is unavailable: $openfoam_bashrc" >&2
        return 69
    fi
    if [[ "$base_python" != /* || ! -x "$base_python" ]]; then
        printf '%s\n' "MANDiFuel startup: Python is unavailable: $base_python" >&2
        return 69
    fi
    if [[ -z "${MANDIFUEL_OFFBEAT_BIN:-}" ||
          "$MANDIFUEL_OFFBEAT_BIN" != /* || ! -d "$MANDIFUEL_OFFBEAT_BIN" ]]; then
        printf '%s\n' "MANDiFuel startup: configured OFFBEAT bin directory is unavailable." >&2
        return 69
    fi
    if [[ -n "${MANDIFUEL_CASE_LIBRARY_ROOT:-}" &&
          ( "$MANDIFUEL_CASE_LIBRARY_ROOT" != /* || ! -d "$MANDIFUEL_CASE_LIBRARY_ROOT" ) ]]; then
        printf '%s\n' "MANDiFuel startup: case-library root is invalid." >&2
        return 69
    fi
    if [[ ! "$MANDIFUEL_RAG_MAPPING_API_KEY_ENV" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ||
          ! "$MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ||
          ! "$MANDIFUEL_RAG_EMBEDDING_DIMENSION" =~ ^[1-9][0-9]*$ ||
          ! "$MANDIFUEL_RAG_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*([.][0-9]+)?$ ||
          ( -n "${MANDIFUEL_RAG_CACHE_DIR:-}" &&
            ( "$MANDIFUEL_RAG_CACHE_DIR" != /* || "$MANDIFUEL_RAG_CACHE_DIR" == "/" ) ) ]]; then
        printf '%s\n' "MANDiFuel startup: RAG provider configuration is invalid." >&2
        return 69
    fi

    set --
    set +u
    set +e
    # shellcheck disable=SC1090
    source "$openfoam_bashrc"
    local source_status=$?
    cd -- "$caller_directory"
    set -e
    set -u
    if (( source_status != 0 )); then
        printf '%s\n' "MANDiFuel startup: failed to load OpenFOAM environment." >&2
        return 69
    fi
    PATH="$MANDIFUEL_OFFBEAT_BIN:$PATH"
    export PATH
    for command_name in blockMesh offbeat; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            printf '%s\n' "MANDiFuel startup: required command is unavailable: $command_name" >&2
            return 69
        fi
    done

    base_python_dir="$(cd -- "$(dirname -- "$base_python")" && pwd -P)"
    task_python="$base_python_dir/python3"
    if [[ ! -x "$task_python" ||
          "$("$task_python" -P -B -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
        printf '%s\n' "MANDiFuel startup: configured python3 is not Python 3.12." >&2
        return 69
    fi
    PATH="$base_python_dir:$PATH"
    export PATH
    python3 -B "$plugin_root/rag/build_index.py" --check >/dev/null

    for command_name in scipy nevergrad optuna; do
        version="$(python3 -P -B -c \
            'import importlib, importlib.metadata, sys; importlib.import_module(sys.argv[1]); print(importlib.metadata.version(sys.argv[1]))' \
            "$command_name" 2>/dev/null || true)"
        if [[ "$version" =~ ^[0-9A-Za-z][0-9A-Za-z.!+_-]{0,79}$ ]]; then
            available_study_libraries+=("$command_name==$version")
        else
            missing_study_libraries+=("$command_name")
        fi
    done

    export MANDIFUEL_CASE_LIBRARY_ROOT
    export MANDIFUEL_RAG_MAPPING_BASE_URL MANDIFUEL_RAG_MAPPING_MODEL
    export MANDIFUEL_RAG_MAPPING_API_KEY_ENV MANDIFUEL_RAG_EMBEDDING_BASE_URL
    export MANDIFUEL_RAG_EMBEDDING_MODEL MANDIFUEL_RAG_EMBEDDING_DIMENSION
    export MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV MANDIFUEL_RAG_CACHE_DIR
    export MANDIFUEL_RAG_TIMEOUT_SECONDS
    mapping_key_name="$MANDIFUEL_RAG_MAPPING_API_KEY_ENV"
    embedding_key_name="$MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV"
    if [[ -n "${!mapping_key_name:-}" && -n "${!embedding_key_name:-}" ]]; then
        rag_provider_status="configured"
    else
        rag_provider_status="API keys unavailable; uncached template retrieval will stop"
    fi

    printf '%s\n' \
        "MANDiFuel plugin root: $plugin_root" \
        "RAG index: 137 case cards, dual index verified" \
        "RAG providers: $rag_provider_status" \
        "OFFBEAT: $(command -v offbeat)" \
        "Task python3: $(command -v python3)" \
        "Case library: ${MANDIFUEL_CASE_LIBRARY_ROOT:-not configured}" \
        "Optional study libraries: ${available_study_libraries[*]:-none}"
    if ((${#missing_study_libraries[@]})); then
        printf '%s\n' "Optional study libraries unavailable: ${missing_study_libraries[*]}." >&2
    fi
}
