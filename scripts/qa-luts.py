#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa-luts.py —— LUT 体检：用灰阶 + 色块探针图跑一遍每个 LUT，判定它是否“正常”。

为什么需要：spektrafilm 的 LUT 必须 胶片×相纸 配对正确。
  * 负片：用胶片自带的 target_print（Portra→portra_endura、Pro 400H→crystal_archive、Vision3→kodak_2383）
  * 正片/幻灯片（Velvia、Kodachrome、Provia、Ektachrome）：profile 里 target_print=null，
    但 `spektrafilm-lut build` 强制要求 --print，硬配相纸会造成二次反相 → 画面几乎全黑。
这个脚本就是用来一眼抓出后者的。

用法：
  python3 scripts/qa-luts.py                # 体检 <root>/luts/*.cube
  python3 scripts/qa-luts.py --dir 某目录
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
import importlib.util
import os
from pathlib import Path
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# 素材/工作目录：优先 FILMSIM_ROOT，其次当前目录；LUT 目录兼容 <root>/<root>/luts 与 <root>/luts
ROOT = Path(os.environ.get("FILMSIM_ROOT", Path.cwd())).expanduser().resolve()


def default_luts() -> Path:
    for cand in (ROOT / "数据" / "luts", ROOT / "luts"):
        if cand.is_dir():
            return cand
    return ROOT / "luts"

PROJ = ROOT

_spec = importlib.util.spec_from_file_location("lr_filmsim", os.path.join(HERE, "lr-filmsim.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)  # type: ignore[union-attr]

# 探针：0-255 灰阶 + 常见色块
GRAY_LEVELS = [0, 16, 32, 64, 128, 192, 224, 255]
PATCHES = {
    "肤色": (0.85, 0.68, 0.58),
    "天空": (0.45, 0.65, 0.92),
    "草木": (0.28, 0.45, 0.20),
    "中性灰": (0.5, 0.5, 0.5),
}


def probe() -> np.ndarray:
    """构造探针图：一行灰度阶梯 + 一行色块（宽 256，高 64）"""
    img = np.zeros((64, 256, 3), dtype=np.float32)
    for i, lv in enumerate(GRAY_LEVELS):
        x0 = int(i * 256 / len(GRAY_LEVELS))
        x1 = int((i + 1) * 256 / len(GRAY_LEVELS))
        img[:, x0:x1] = lv / 255.0
    for j, rgb in enumerate(PATCHES.values()):
        x = 8 + j * 60
        img[40:56, x:x + 48] = rgb
    return img


def analyze(name: str, path: str, probe_img: np.ndarray) -> dict:
    lut, lut1d = core.load_lut(path)
    out = core.apply_lut(probe_img, lut, lut1d, 1.0, False)

    idx = {lv: int(i * 256 / len(GRAY_LEVELS)) for i, lv in enumerate(GRAY_LEVELS)}
    grays = {lv: out[0, idx[lv]] for lv in GRAY_LEVELS}
    mid = grays[128]                      # 中灰输出
    white = grays[255]
    black = grays[16]
    mid_lum = float(mid.mean())
    white_lum = float(white.mean())
    black_lum = float(black.mean())

    # 故障特征：曲线反相（暗部比高光还亮）或高光被压死。注意这里数值是 0~1
    ok = (white_lum - black_lum) > (20 / 255.0) and white_lum > (96 / 255.0)
    return {
        "name": name,
        "mid": mid, "mid_lum": mid_lum,
        "white_lum": white_lum, "black_lum": black_lum,
        "contrast": white_lum - black_lum,
        "ok": ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="LUT 体检（灰阶探针）")
    ap.add_argument("--dir", default=str(default_luts()))
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.dir, "*.cube")) + glob.glob(os.path.join(args.dir, "*.png")))
    if args.only:
        paths = [p for p in paths if any(k.lower() in os.path.basename(p).lower() for k in args.only)]
    if not paths:
        print("没有 LUT", file=sys.stderr)
        return 2

    img = probe()
    print(f"{'LUT':34s} {'中灰→RGB':>18s} {'中灰亮':>7s} {'高光亮':>7s} {'暗部亮':>7s} {'动态':>6s}  判定")
    print("-" * 104)
    bad = []
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        if name.startswith("identity"):
            continue
        try:
            r = analyze(name, p, img)
        except SystemExit as e:  # 无效 LUT
            print(f"{name:34s} 解析失败：{e}")
            bad.append(name)
            continue
        flag = "✓ 正常" if r["ok"] else "✗ 可疑（相纸配错/正片硬配相纸）"
        if not r["ok"]:
            bad.append(name)
        rgb = "[" + " ".join(f"{v*255:3.0f}" for v in r["mid"]) + "]"
        print(f"{name:34s} {rgb:>18s} {r['mid_lum']*255:7.1f} {r['white_lum']*255:7.1f} "
              f"{r['black_lum']*255:7.1f} {r['contrast']*255:6.1f}  {flag}")

    print()
    if bad:
        print(f"⚠︎ {len(bad)} 个可疑：{'、'.join(bad)}")
        print("  修法：负片换用胶片自带的相纸（见 profile 的 target_print）；正片（Velvia/Kodachrome/Provia/Ektachrome）")
        print("  在 CLI 里无法正确烘（没有 no-print 选项），别用 —— 需要正片外观就用负片近似或等上游支持。")
        return 1
    print("全部正常 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
