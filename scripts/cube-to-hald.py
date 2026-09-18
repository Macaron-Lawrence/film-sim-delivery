#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cube-to-hald.py —— 把 .cube LUT 转成 HaldCLUT PNG。

为什么：ART（以及 RawTherapee）的 **Film Simulation** 工具只吃 HaldCLUT PNG，
不接受 Adobe .cube（实测 ART 1.26.8 的 --check-lut 对 .cube 直接报 Invalid）。
.cube 想进 ART，就得转成 Hald。

Hald level 8 = 每通道 64 级、512×512 像素；我们用三线性从原 LUT 重采样。

用法：
  python3 scripts/cube-to-hald.py                    # 转换 <root>/luts/*.cube
  python3 scripts/cube-to-hald.py --level 12         # 更高精度（147.5 MB/张，一般不必）
  python3 scripts/cube-to-hald.py --out <root>/art/clut
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import os
from pathlib import Path

import numpy as np
from PIL import Image

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


def cube_to_hald(cube: Path, level: int, pre_gain: float = 0.3472) -> Image.Image:
    """pre_gain：把 spektrafilm 的"+4 档曝光定位"补偿掉。
    spektrafilm bundle 内部对线性值乘 2.88（源白点放在 +4 档），直接套会亮约 1.5 档；
    默认 0.3472 = 1/2.88 把中灰放回原位（与 lr-filmsim.py 的 --pre-gain 一致）。
    传 1.0 则保留原始（未补偿）映射。"""
    lut, lut1d = core.load_lut(str(cube))
    n = level * level                        # 每通道级数 = level^2
    if n > 128:
        raise SystemExit(f"level {level} → 每通道 {n} 级过大，建议 8~11")
    if abs(pre_gain - 1.0) > 1e-6:
        # 输入先在"编码域"做曝光位移：x' = encode(decode(x) * g)，再查原 LUT
        pass
    idx = np.arange(n ** 3, dtype=np.int64)
    r = idx % n
    g = (idx // n) % n
    b = idx // (n * n)
    pts = np.stack([r, g, b], axis=-1).astype(np.float32) / (n - 1)
    if abs(pre_gain - 1.0) > 1e-6:
        pts = core.linear_to_srgb(core.srgb_to_linear(pts) * pre_gain).astype(np.float32)
    # 1D shaper 先过一遍（如有），保持与 lr-filmsim 一致
    if lut1d is not None:
        n1 = lut1d.shape[0]
        c = np.clip(pts, 0, 1) * (n1 - 1)
        j0 = np.floor(c).astype(np.int64)
        f = (c - j0).astype(np.float32)
        j1 = np.minimum(j0 + 1, n1 - 1)
        l1 = lut1d.astype(np.float32)
        pts = (1 - f) * l1[j0.reshape(-1)].reshape(pts.shape) + f * l1[j1.reshape(-1)].reshape(pts.shape)
    out = core._apply_3d(lut.astype(np.float32), pts.reshape(1, -1, 3)[0])
    side = level ** 3                        # 图像边长 = level^3
    img = np.clip(out, 0, 1).reshape(side, side, 3)
    return Image.fromarray((img * 255.0 + 0.5).astype(np.uint8))


def main() -> int:
    ap = argparse.ArgumentParser(description=".cube → HaldCLUT PNG（给 ART/RawTherapee 用）")
    ap.add_argument("--dir", default=str(default_luts()))
    ap.add_argument("--out", default=None, help="输出目录，默认与输入同目录")
    ap.add_argument("--level", type=int, default=8, help="Hald level（8 → 512×512）")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--pre-gain", type=float, default=0.3472,
                    help="线性域预增益（抵消 spektrafilm 的 +4 档定位），1.0=不补偿")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cubes = sorted(glob.glob(os.path.join(args.dir, "*.cube")))
    if args.only:
        cubes = [c for c in cubes if any(k.lower() in os.path.basename(c).lower() for k in args.only)]
    if not cubes:
        print("没有 .cube")
        return 2

    for c in cubes:
        name = os.path.splitext(os.path.basename(c))[0]
        if name.startswith("identity"):
            continue
        img = cube_to_hald(Path(c), args.level, args.pre_gain)
        suffix = "_hald%d.png" % args.level if abs(args.pre_gain - 1.0) > 1e-6 else "_hald%d_raw.png" % args.level
        dst = out_dir / (name + suffix)
        img.save(dst)
        print(f"{os.path.basename(c):28s} -> {dst.name}  ({img.width}×{img.height})")
    print("\n用法：ART 的 Film Simulation 工具里选择这些 PNG（CLUT 目录已指向 <root>/art/clut）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
