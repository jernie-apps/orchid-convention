#!/usr/bin/env bash
# hook.sh - single entry point for every convention-core hook.
#
# Usage: hook.sh <guard|lint|gate|baseline> [--host claude]
#
# Reads the host's hook payload on stdin and hands it to the matching Python
# layer. Kept to bash 3.2 (macOS) and POSIX tools. When the layer cannot run
# at all, it says so in the host's systemMessage instead of exiting quietly:
# a hook that did not run is never a pass.

layer="${1:-}"
case "$layer" in
  guard|lint) script="orchid_$layer.py"; shift ;;
  gate|baseline) script="orchid_gate.py" ;;
  *)
    echo "usage: hook.sh <guard|lint|gate|baseline> [--host claude]" >&2
    exit 2
    ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"
python="${ORCHID_PYTHON:-python3}"

if ! command -v "$python" >/dev/null 2>&1; then
  # Drain stdin so the host never sees a broken pipe.
  cat >/dev/null
  printf '{"systemMessage":"Orchid convention %s did not run: %s is not on PATH. Nothing was checked."}\n' \
    "$layer" "$python"
  exit 0
fi

exec "$python" -I "$here/$script" "$@"
