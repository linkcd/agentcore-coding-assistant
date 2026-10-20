#!/bin/sh
# The native uvx stub requires /proc/self/exe, which Codex's minimal sandbox hides.
if [ "$#" -eq 1 ]; then
    case "$1" in --version|-V) exec /usr/local/bin/uv --version ;; esac
fi
exec /usr/local/bin/uv tool run "$@"
