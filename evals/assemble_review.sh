#!/usr/bin/env bash
# assemble_review.sh —— 把各次评测的产物整理成 skill-creator 的 viewer 期望的目录结构，
# 并生成一个静态 HTML 复核页。
#
#   bash evals/assemble_review.sh [workspace]      # 默认 /tmp/filmeval/review
#
# 输入约定（与 evals/evals.json 对应）：
#   <workspace>/../run-baseline-A|run-withskill-A  → eval 0
#   <workspace>/../run-baseline-B|run-withskill-B  → eval 1
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$HERE/.." && pwd)"
WS="${1:-/tmp/filmeval/review}"
SRC_ROOT="$(dirname "$WS")"
ITER="$WS/iteration-1"
# 找 skill-creator 的复核页生成器：环境变量 > 常见位置 > PATH
VIEWER="${VIEWER:-}"
if [ -z "$VIEWER" ]; then
  for c in "$HOME/.claude/skills/skill-creator/eval-viewer/generate_review.py" \
           "$HOME/.dsh/skills/skill-creator/eval-viewer/generate_review.py" \
           "$HOME/.config/skill-creator/eval-viewer/generate_review.py"; do
    [ -f "$c" ] && VIEWER="$c" && break
  done
fi

mkdir -p "$ITER"

place() {  # place <eval-dir-name> <eval-id> <config> <src-run-dir>
  local d="$ITER/$1/$3"; mkdir -p "$d/outputs"
  local s="$4"
  [ -d "$s" ] || { echo "  （缺 ${s}，跳过）"; return; }
  # 只复制产物：排除 venv / 缓存 / ndarray 之类的中间件
  (cd "$s" && find . -type f \
      -not -path "*/.venv/*" -not -path "*/__pycache__/*" -not -name "*.npy" \
      -not -path "*/work/*" -not -name "*.log" -print0 \
    | while IFS= read -r -d '' f; do
        mkdir -p "$d/outputs/$(dirname "$f")"
        cp -f "$f" "$d/outputs/$f" 2>/dev/null || true
      done)
  # 报告文本 → 供评分脚本用
  if [ -f "$s/report.txt" ]; then cp -f "$s/report.txt" "$d/report.txt"; fi
  if [ -f "$s/grading.json" ]; then cp -f "$s/grading.json" "$d/grading.json"; fi
  echo "  $1/$3 ← $s"
}

mkdir -p "$ITER/deliver-cube-to-lightroom" "$ITER/diagnose-washed-out-profile"
place deliver-cube-to-lightroom 0 with_skill    "$SRC_ROOT/run-withskill-A"
place deliver-cube-to-lightroom 0 without_skill "$SRC_ROOT/run-baseline-A"
place diagnose-washed-out-profile 1 with_skill    "$SRC_ROOT/run-withskill-B"
place diagnose-washed-out-profile 1 without_skill "$SRC_ROOT/run-baseline-B"

# 把 evals.json 里的断言搬进 eval_metadata.json
python3 - "$ITER" "$HERE/evals.json" <<'PY'
import json, sys
from pathlib import Path
iter_dir, evals_json = Path(sys.argv[1]), Path(sys.argv[2])
evals = json.loads(evals_json.read_text(encoding="utf-8"))["evals"]
for ev in evals:
    d = iter_dir / ev["eval_name"]
    meta = {"eval_id": ev["id"], "eval_name": ev["eval_name"],
            "prompt": ev["prompt"], "assertions": ev["assertions"]}
    (d / "eval_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
print("已写入 eval_metadata.json")
PY

# generate_review.py 需要 Python >=3.10（用了 X | None 语法），自动挑一个
VIEW_PY=""
for c in "${VIEWER_PY:-}" "$(command -v python3.13)" "$(command -v python3.12)" "$(command -v python3.11)" "$(command -v python3.10)" "$(command -v python3)"; do
  [ -n "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null && VIEW_PY="$c" && break
done

if [ -f "$VIEWER" ] && [ -n "$VIEW_PY" ]; then
  OUT="$WS/review.html"
  "$VIEW_PY" "$VIEWER" "$ITER" --skill-name film-sim-delivery --static "$OUT" >/dev/null 2>&1 \
    && echo "✓ 复核页：${OUT}（解释器 ${VIEW_PY}）" \
    || echo "⚠ 生成复核页失败（可手动跑：$VIEW_PY $VIEWER $ITER --static ${OUT}）"
else
  echo "（未找到 generate_review.py 或没有 >=3.10 的解释器，跳过复核页；可设 VIEWER_PY=<python3.13 路径>）"
fi
echo "工作区：$ITER"
