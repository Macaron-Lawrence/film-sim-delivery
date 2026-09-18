#!/usr/bin/env bash
# 套版：把胶片 LUT 套到 TIFF / PNG / JPEG 上。一条命令。
#
#   ./apply-look.sh --ls                                 # 看有哪些可用的版
#   ./apply-look.sh portra400 photo.tif                  # 原地改写（LR 外部编辑器的行为）
#   ./apply-look.sh portra400 --out 成品 photo.tif       # 另存到 成品/photo_filmsim.tif
#   ./apply-look.sh portra400 --strength 0.6 photo.tif   # 半强度
#   ./apply-look.sh portra400 照片目录/                   # 整个目录批处理
#
# 曝光定位：spektrafilm 的 bundle 把"源白点放在 +4 档"，直接套会亮约 1.5 档。
# 默认 PRE_GAIN=0.3472（=1/2.88）把中灰放回原位；想要"原样套"就加 --flat。
#
# 第一个参数是模糊匹配的胶片名，例如：portra400 / portra / 400h / ektar / velvia / gold / vision3
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# 素材根目录：FILMSIM_ROOT 优先，其次当前目录
ROOT="${FILMSIM_ROOT:-$PWD}"
if [ -d "$ROOT/数据/luts" ]; then LUTS="$ROOT/数据/luts"; else LUTS="$ROOT/luts"; fi
# Python：优先同级/根目录下的 venv，其次系统 python3
for c in "$ROOT/.venv-lr/bin/python" "$ROOT/.venv/bin/python"; do
  [ -x "$c" ] && PY="$c" && break
done
PY="${PY:-$(command -v python3)}"
APPLIER="$HERE/lr-filmsim.py"

list_luts() {
  find "$LUTS" \( -name '*.cube' -o -name '*.png' \) -type f 2>/dev/null \
    | sed "s|$LUTS/||" | sort | sed 's|^|  |'
}

if [ $# -eq 0 ] || [ "${1:-}" = "--ls" ]; then
  echo "可用的版（数据/luts/）："
  list_luts
  echo
  echo "用法： $0 <胶片简写> [--out 目录] [--strength 0~1] [--linear-pipeline] <文件或目录>..."
  exit 0
fi

WANT="$1"; shift

LUT=""
for cand in "$LUTS/$WANT.cube" "$LUTS/$WANT.png"; do
  [ -f "$cand" ] && LUT="$cand" && break
done
if [ -z "$LUT" ]; then
  LUT="$(find "$LUTS" -maxdepth 1 \( -name '*.cube' -o -name '*.png' \) -type f 2>/dev/null | grep -i -- "$WANT" | sort | head -1 || true)"
fi
if [ -z "$LUT" ]; then
  LUT="$(find "$LUTS" \( -name '*.cube' -o -name '*.png' \) -type f 2>/dev/null | grep -i -- "$WANT" | sort | head -1 || true)"
fi
if [ -z "$LUT" ]; then
  echo "找不到匹配 '$WANT' 的 LUT。可选：" >&2
  list_luts >&2
  exit 1
fi
LUT_NAME="$(basename "$LUT" | sed -E 's/^lut_v[0-9]+_//; s/\.(cube|png)$//; s/_portraendura$//')"
echo "套版：$(basename "$LUT")"

OUT=""; STRENGTH=""; LINEAR=""; SUFFIX=""; PREGAIN="${PRE_GAIN:-0.3472}"; POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:-}"; shift 2 ;;
    --strength) STRENGTH="${2:-}"; shift 2 ;;
    --suffix) SUFFIX="${2:-}"; shift 2 ;;
    --linear-pipeline) LINEAR="--linear-pipeline"; shift ;;
    --pre-gain) PREGAIN="${2:-}"; shift 2 ;;
    --flat|--no-pre-gain) PREGAIN="1.0"; shift ;;
    --) shift; while [ $# -gt 0 ]; do POS+=("$1"); shift; done ;;
    *) POS+=("$1"); shift ;;
  esac
done

FILES=()
for p in ${POS[@]+"${POS[@]}"}; do
  if [ -d "$p" ]; then
    while IFS= read -r -d '' f; do FILES+=("$f"); done < <(find "$p" -maxdepth 1 -type f \
      \( -iname '*.tif' -o -iname '*.tiff' -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print0 | sort -z)
  else
    FILES+=("$p")
  fi
done

if [ ${#FILES[@]} -eq 0 ]; then echo "没有可处理的文件" >&2; exit 1; fi

ARGS=("--lut" "$LUT")
[ -n "$OUT" ] && ARGS+=("--out" "$OUT")
[ -n "$STRENGTH" ] && ARGS+=("--strength" "$STRENGTH")
[ -n "$LINEAR" ] && ARGS+=("--linear-pipeline")
# --out 模式下默认按胶片名加后缀，避免多套外观互相覆盖
ARGS+=("--suffix" "${SUFFIX:-_${LUT_NAME}}")
[ -n "$PREGAIN" ] && ARGS+=("--pre-gain" "$PREGAIN")

"$PY" "$APPLIER" "${ARGS[@]}" ${FILES[@]+"${FILES[@]}"}
echo "完成 ${#FILES[@]} 张。"
