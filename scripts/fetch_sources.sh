#!/usr/bin/env bash
# fetch_sources.sh —— 按 references/sources.md 里的清单拉取上游开源 LUT 素材（**不打包进 skill**）
#
#   ./fetch_sources.sh                 # 列出可拉取的来源
#   ./fetch_sources.sh rt              # 拉 RawTherapee HaldCLUT 集合（402MB）
#   ./fetch_sources.sh spectra         # 装 spectral_film_lut（pip，用于现烘卷）
#   ./fetch_sources.sh fuji            # 拉 Fujifilm 创意配置包
#   SRC_DIR=~/film-sources ./fetch_sources.sh rt
#
# 所有素材落在 $SRC_DIR（默认 $FILMSIM_ROOT/sources），skill 目录本身不含任何 LUT 数据。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${FILMSIM_ROOT:-$PWD}"
SRC_DIR="${SRC_DIR:-$ROOT/sources}"

list() {
  cat <<'TXT'
可拉取的来源（详见 references/sources.md）：
  rt        RawTherapee Film Simulation Collection —— 295 个 HaldCLUT（CC BY-SA 4.0）
  spectra   spectral_film_lut（MIT）—— pip 安装，87 个卷现烘，含黑白/正片/电影印片
  fuji      TingfengLuo/Camera-Profile-for-Fujifilm-Film-Simulation —— 11 款 Fuji 风格 + 1464 个线性基底 dcp
  adobe     无需下载：Adobe 随 Lightroom 自带 "Film-Inspired 01–12"（在应用包 Settings/Premium/ 里）
  spektra   用 uv 安装 spektrafilm（GPLv3）—— 光谱物理模拟，可烘 LUT 或与 ART 联动
不可自动拉取（许可不明，仅个人使用；见 sources.md）：
  abpy/FujifilmCameraProfiles、jeremieLouvaert/ComfyUI-Darkroom
TXT
}

case "${1:-}" in
  ""|--list|-l) list ;;

  rt)
    mkdir -p "$SRC_DIR"
    echo "== RawTherapee Film Simulation Collection =="
    echo "许可：CC BY-SA 4.0（包内 README.txt）｜署名 Pat David / Pavlov Dmitry / Michael Ezra"
    echo "如果用它做分发或商用的衍生，请保留署名并同样以 CC BY-SA 4.0 发布。"
    cd "$SRC_DIR"
    curl -L --retry 3 -C - -o HaldCLUT.zip "http://rawtherapee.com/shared/HaldCLUT.zip"
    unzip -q -o HaldCLUT.zip
    echo "✓ 解压到 $SRC_DIR/HaldCLUT（$(find HaldCLUT -name '*.png' | wc -l | tr -d ' ') 个）"
    echo "下一步：python3 scripts/curate-rt-halclut.py --src $SRC_DIR/HaldCLUT"
    ;;

  spectra)
    mkdir -p "$SRC_DIR"
    echo "== spectral_film_lut（MIT）=="
    if command -v uv >/dev/null 2>&1; then
      uv venv --python 3.13 "$SRC_DIR/.venv-spectral" 2>/dev/null || python3 -m venv "$SRC_DIR/.venv-spectral"
      uv pip install --python "$SRC_DIR/.venv-spectral/bin/python" spectral_film_lut
    else
      python3 -m venv "$SRC_DIR/.venv-spectral"
      "$SRC_DIR/.venv-spectral/bin/pip" install -q spectral_film_lut
    fi
    echo "✓ 装好：$SRC_DIR/.venv-spectral"
    echo "下一步：$SRC_DIR/.venv-spectral/bin/python scripts/bake-spectral-luts.py --list"
    ;;

  fuji)
    mkdir -p "$SRC_DIR"
    echo "== Fujifilm 创意配置包（仓库未声明许可，仅个人使用）=="
    cd "$SRC_DIR"
    git clone --depth 1 https://github.com/TingfengLuo/Camera-Profile-for-Fujifilm-Film-Simulation.git fuji || true
    echo "✓ $SRC_DIR/fuji"
    echo "安装：把 Fujifilm Simulation LUT/*.xmp 复制到 Adobe CameraRaw/Settings/，"
    echo "      Adobe Standard Linear Profile/*.dcp 复制到 Adobe CameraRaw/CameraProfiles/"
    ;;

  spektra)
    echo "== spektrafilm（GPLv3）=="
    if command -v uv >/dev/null 2>&1; then
      uv tool install --python 3.13 "git+https://github.com/andreavolpato/spektrafilm.git"
      echo "✓ 已装 spektrafilm / spektrafilm-lut"
    else
      echo "需要 uv：curl -LsSf https://astral.sh/uv/install.sh | sh"
      exit 1
    fi
    ;;

  *) list ;;
esac
