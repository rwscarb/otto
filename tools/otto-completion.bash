# otto bash/zsh tab completion
# Source this file or add to ~/.bashrc / ~/.zshrc:
#   source /path/to/otto/tools/otto-completion.bash

# ── make targets ──────────────────────────────────────────────────────────────

_otto_make_targets() {
    local targets
    targets=$(grep -E '^[a-zA-Z_-]+:.*##' Makefile 2>/dev/null | awk -F: '{print $1}')
    echo "$targets"
}

_otto_make_completion() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local targets
    targets=$(_otto_make_targets)
    COMPREPLY=($(compgen -W "$targets" -- "$cur"))
}

# ── otto env vars ─────────────────────────────────────────────────────────────

_OTTO_ENV_VARS=(
    OTTO_ENABLED
    OTTO_PRIVKEY
    OTTO_PUBKEY
    OTTO_LAT
    OTTO_LON
    OTTO_STATION
    OTTO_RELAYS
    OTTO_BTC_WIF
    OTTO_BTC_NETWORK
    OTTO_ANCHOR_EVERY
    OTTO_MODEL
)

_otto_env_completion() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local vars
    vars=$(printf '%s\n' "${_OTTO_ENV_VARS[@]}" | sed 's/$/=/')
    COMPREPLY=($(compgen -W "$vars" -- "$cur"))
}

# ── python -m otto.* submodule completion ─────────────────────────────────────

_otto_modules=(
    otto.node
    otto.aggregator
    otto.consensus
    otto.reputation
    otto.anchor
    otto.events
)

_otto_python_completion() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"
    if [[ "$prev" == "-m" ]]; then
        COMPREPLY=($(compgen -W "${_otto_modules[*]}" -- "$cur"))
    fi
}

# ── Register completions ──────────────────────────────────────────────────────

# make <target> inside otto directory
complete -F _otto_make_completion make

# env var prefix completion: type OTTO_<TAB>
complete -F _otto_env_completion otto-env

# python -m <module>
complete -F _otto_python_completion python3
complete -F _otto_python_completion python

# ── zsh compatibility ─────────────────────────────────────────────────────────
# If running zsh with bashcompinit, this file works as-is.
# Native zsh users: add to ~/.zshrc:
#   autoload -U bashcompinit && bashcompinit
#   source /path/to/otto/tools/otto-completion.bash
