#!/usr/bin/env bash
# POSIX 包装：真正的安装逻辑在 install_ccprofiles.py（跨平台）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=""
for c in "${FILMSIM_ROOT:-$PWD}/.venv-lr/bin/python" "${FILMSIM_ROOT:-$PWD}/.venv/bin/python" "$(command -v python3)"; do
  [ -x "$c" ] && PY="$c" && break
done
[ -n "$PY" ] || { echo "找不到 python3"; exit 1; }
ACTION="install"
case "${1:-}" in --list) ACTION="list";; --remove) ACTION="remove";; esac
exec "$PY" "$HERE/install_ccprofiles.py" "$ACTION" "${@:2}"
