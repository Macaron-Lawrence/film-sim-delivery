#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate-luts.py —— 给每个 LUT 算一个"曝光定位"预增益（pre-gain），输出 JSON。

为什么需要：不同来源的 LUT 曝光定位不一样，所以每个 LUT 需要单独标定，不能共用同一个系数。
早期文档报告过一些来源的具体落点（spektrafilm 的 +4 档 → 0.3472、spectral_film_lut 的中灰区间、
黑白卷偏暗等），这些属于**未归档的历史报告值**（见 references/calibration.md §0）：
那批 LUT 的清单与完整校准输出没有随仓库保存，因此**不要沿用**，对当前输入重新测量即可——
本脚本存在的意义就是当场算出来。

两种标定模式：
  midgray    让输入中灰 128 映射回 128（影调定位"正确"，推荐）
  brightness 让一组中性色阶的平均亮度尽量不变（观感亮度一致，中灰会略亮）

用法：
  python3 scripts/calibrate-luts.py                       # 标定 <root>/luts 下全部
  python3 scripts/calibrate-luts.py --dir <root>/luts/spectral --mode midgray
  python3 scripts/calibrate-luts.py --out <root>/luts/_calibration.json
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
import json
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# 素材/工作目录：优先 FILMSIM_ROOT，其次当前目录；LUT 目录兼容 <root>/<root>/luts 与 <root>/luts
ROOT = Path(os.environ.get("FILMSIM_ROOT", Path.cwd())).expanduser().resolve()


def default_luts() -> Path:
    for cand in (ROOT / "数据" / "luts", ROOT / "luts"):
        if cand.is_dir():
            return cand
    return ROOT / "luts"


def _p(p) -> Path:
    """把旧代码里的 PROJ / "数据" / "luts" 之类调用重定向到新根目录。"""
    return ROOT / Path(*p.parts[1:]) if p.parts and p.parts[0] in ("数据",) else p

PROJ = ROOT

_spec = importlib.util.spec_from_file_location("lr_filmsim", str(HERE / "lr-filmsim.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)  # type: ignore[union-attr]

LEVELS = np.array([0, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128,
                   144, 160, 176, 192, 208, 224, 240, 255], dtype=np.float32) / 255.0


def neutral_out(lut, gain: float, protect: float = 0.0) -> np.ndarray:
    pts = np.repeat(LEVELS[:, None], 3, axis=1)
    out = core.apply_lut(pts[None], lut, None, 1.0, False, gain)[0]
    if protect > 0.0:                      # 与生成器里的"护高光"混合保持一致
        lum = pts.mean(axis=1)
        t = np.clip((lum - protect) / max(1e-6, 1.0 - protect), 0.0, 1.0)
        w = 1.0 - (t * t * (3.0 - 2.0 * t))
        out = out * w[:, None] + pts * (1.0 - w[:, None])
    return out.mean(axis=1)


def calibrate(lut, mode: str, protect: float = 0.0) -> tuple[float, dict]:
    lo, hi = 0.10, 4.0

    def score(g: float) -> float:
        out = neutral_out(lut, g, protect)
        if mode == "midgray":
            return float(out[np.argmin(np.abs(LEVELS - 0.5))] - 0.5)
        # brightness：按"感知均匀"的权重看整体亮度偏差
        w = np.linspace(0.2, 1.0, len(LEVELS))
        return float((out * w).sum() / w.sum() - (LEVELS * w).sum() / w.sum())

    # 二分求根（score 随 gain 单调）
    for _ in range(40):
        mid = (lo + hi) / 2
        if score(mid) > 0:
            hi = mid
        else:
            lo = mid
    g = (lo + hi) / 2
    out0 = neutral_out(lut, 1.0, protect)
    outg = neutral_out(lut, g, protect)
    idx = int(np.argmin(np.abs(LEVELS - 0.5)))
    return g, {
        "mid_in": int(round(LEVELS[idx] * 255)),
        "mid_out_before": round(float(out0[idx]) * 255, 1),
        "mid_out_after": round(float(outg[idx]) * 255, 1),
        "white_before": round(float(out0[-1]) * 255, 1),
        "white_after": round(float(outg[-1]) * 255, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="为每个 LUT 标定曝光定位预增益")
    ap.add_argument("--dir", default=str(default_luts()),
                    help="含 *.cube / HaldCLUT *.png 的目录")
    ap.add_argument("--mode", choices=["midgray", "brightness"], default="midgray")
    ap.add_argument("--out", default=str(PROJ / "数据" / "luts" / "_calibration.json"))
    ap.add_argument("--protect", type=float, default=0.0,
                    help="护高光阈值（与生成器的 --protect 保持一致）")
    ap.add_argument("--merge", action="store_true",
                    help="与已有 JSON 合并（不覆盖其它目录的标定结果）")
    args = ap.parse_args()

    cubes = sorted(glob.glob(os.path.join(args.dir, "*.cube"))
                   + glob.glob(os.path.join(args.dir, "*.png"))
                   + glob.glob(os.path.join(args.dir, "*.tif")))
    cubes = [c for c in cubes if not os.path.basename(c).startswith("identity")]
    if not cubes:
        print(f"{args.dir} 里没有 .cube")
        return 2

    result: dict[str, dict] = {}
    out_path = Path(args.out)
    if args.merge and out_path.exists():
        result = json.loads(out_path.read_text(encoding="utf-8"))

    print(f"{'LUT':26s} {'pre-gain':>9s} {'中灰 前→后':>16s} {'纯白 前→后':>16s}")
    print("-" * 74)
    for c in cubes:
        stem = os.path.splitext(os.path.basename(c))[0]
        lut, _ = core.load_lut(c)
        g, info = calibrate(lut, args.mode, args.protect)
        result[stem] = {"pre_gain": round(g, 4), "mode": args.mode,
                        "protect": args.protect, **info}
        print(f"{stem:26s} {g:9.4f} {info['mid_out_before']:7.1f} → {info['mid_out_after']:6.1f} "
              f"{info['white_before']:7.1f} → {info['white_after']:6.1f}")

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共标定 {len(cubes)} 个 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
