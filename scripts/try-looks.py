#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
try-looks.py —— 试版：一张图批量套多版胶片 LUT，并拼成对比图，用来挑外观。

用法：
  python3 scripts/try-looks.py 照片.tif                        # 全部 10 版
  python3 scripts/try-looks.py 照片.tif --only portra ektar velvia
  python3 scripts/try-looks.py 照片.tif --size 1400 --cols 3 --out 试版
  输出：试版/<照片>_<版>.jpg  +  试版/对比图.jpg（带版名的拼图）
"""

from __future__ import annotations

# Windows 上输出被重定向时控制台默认用 cp1252，打印中文/符号会 UnicodeEncodeError。
# 这里把 stdout/stderr 固定成 UTF-8；任何失败都静默跳过，不影响其他平台。
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
del _sys

import argparse
import glob
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
# 素材/工作目录：优先 FILMSIM_ROOT，其次当前目录；LUT 目录兼容 <root>/<root>/luts 与 <root>/luts
ROOT = Path(os.environ.get("FILMSIM_ROOT", Path.cwd())).expanduser().resolve()


def default_luts() -> Path:
    for cand in (ROOT / "数据" / "luts", ROOT / "luts"):
        if cand.is_dir():
            return cand
    return ROOT / "luts"

PROJ = ROOT

# 核心脚本文件名带连字符，不能直接 import，用 importlib 加载
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("lr_filmsim", os.path.join(HERE, "lr-filmsim.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)  # type: ignore[union-attr]


def load_looks(lut_dir: str, only: list[str]) -> list[tuple[str, str]]:
    out = []
    for p in sorted(glob.glob(os.path.join(lut_dir, "*.cube")) + glob.glob(os.path.join(lut_dir, "*.png"))):
        name = os.path.splitext(os.path.basename(p))[0]
        if name.startswith("identity") or name.startswith("_"):
            continue
        if only and not any(k.lower() in name.lower() for k in only):
            continue
        out.append((name, p))
    return out


def resize_max(img: Image.Image, size: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= size:
        return img
    s = size / max(w, h)
    return img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser(description="批量试版并生成对比图")
    ap.add_argument("image")
    ap.add_argument("--lut-dir", default=str(default_luts()))
    ap.add_argument("--only", nargs="*", default=None, help="只试这些（模糊匹配）")
    ap.add_argument("--out", default=None, help="输出目录，默认 <项目>/试版")
    ap.add_argument("--size", type=int, default=1600, help="每格长边像素")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--linear-pipeline", action="store_true")
    ap.add_argument("--pre-gain", type=float, default=0.3472,
                    help="线性域预增益，默认 0.3472 把中灰放回原位；1.0=原样套")
    args = ap.parse_args()

    out_dir = args.out or str(ROOT / "contact-sheets")
    os.makedirs(out_dir, exist_ok=True)

    looks = load_looks(args.lut_dir, args.only)
    if not looks:
        print("没有找到可试的 LUT", file=sys.stderr)
        return 2

    base = Image.open(args.image).convert("RGB")
    thumb = resize_max(base, args.size)
    arr = np.asarray(thumb, dtype=np.float32) / 255.0

    stem = os.path.splitext(os.path.basename(args.image))[0]
    tiles: list[tuple[str, Image.Image]] = []

    for i, (name, lut_path) in enumerate(looks, 1):
        try:
            lut, lut1d = core.load_lut(lut_path)
        except SystemExit as e:
            print(f"跳过 {name}: {e}", file=sys.stderr)
            continue
        res = core.apply_lut(arr, lut, lut1d, args.strength, args.linear_pipeline, args.pre_gain)
        img = Image.fromarray(np.rint(res * 255.0).astype(np.uint8))
        path = os.path.join(out_dir, f"{stem}_{name}.jpg")
        img.save(path, quality=92)
        tiles.append((name, img))
        print(f"[{i}/{len(looks)}] {name} -> {os.path.basename(path)}")

    # 拼对比图
    if tiles:
        cw = max(t[1].width for t in tiles)
        ch = max(t[1].height for t in tiles)
        bar = 26
        cols = max(1, min(args.cols, len(tiles)))
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows * (ch + bar)), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for idx, (name, img) in enumerate(tiles):
            r, c = divmod(idx, cols)
            x, y = c * cw, r * (ch + bar)
            sheet.paste(img, (x + (cw - img.width) // 2, y + bar + (ch - img.height) // 2))
            label = name.replace("_", " ")[: int(cw / 7)]
            draw.text((x + 8, y + 6), label, fill=(235, 235, 235))
        sheet_path = os.path.join(out_dir, "对比图.jpg")
        sheet.save(sheet_path, quality=90)
        print(f"\n对比图：{sheet_path}  （{len(tiles)} 版）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
