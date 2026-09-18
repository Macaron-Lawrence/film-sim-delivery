#!/usr/bin/env bash
# POSIX 包装：真正的自检逻辑在 selftest.py（跨平台，Windows 也能直接跑）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=""
for c in "${FILMSIM_ROOT:-$PWD}/.venv-lr/bin/python" "${FILMSIM_ROOT:-$PWD}/.venv/bin/python" "$(command -v python3)"; do
  [ -x "$c" ] && PY="$c" && break
done
[ -n "$PY" ] || { echo "找不到 python3"; exit 1; }
exec "$PY" "$HERE/selftest.py" "$@"
