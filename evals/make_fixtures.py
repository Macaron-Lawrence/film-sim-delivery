#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fixtures.py —— 生成评测样本（可复现，不依赖任何上游 LUT 数据）。

评测用的是**合成**的胶片 LUT 与两个"坏样本"，所以仓库里不需要放任何第三方 LUT，
也不用担心上游许可。跑一次这个脚本，就能在 evals/fixtures/ 下得到：

  luts/portra_like.cube            合成胶片 LUT（暖调 + 抬暗部 + 压高光），33³
  bad/portra_noprotect.xmp         空间/元数据都对，但 **没有护高光** → 纯白封顶 ~214
  bad/portra_spacemismatch.xmp     按线性族烘的表格，却按显示域声明 → 整张发灰

用法： python3 evals/make_fixtures.py [--out evals/fixtures]
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synth_lut(path: Path, n: int = 33) -> None:
    """合成一个形状像真胶片的 LUT：抬暗部、压高光、轻微暖调（完全自制，无上游数据）。"""
    r, g, b = np.meshgrid(*[np.linspace(0, 1, n)] * 3, indexing="ij")
    rgb = np.transpose(np.stack([r, g, b], -1), (2, 1, 0, 3))     # [b][g][r] = .cube 顺序
    # 胶片印片形状：抬暗部 + 肩部封顶（白点约 0.85），这正是"缺护高光"会暴露的地方
    y = 0.05 + 0.80 * np.power(rgb, 1.2)
    y[..., 0] = np.clip(y[..., 0] * 1.03, 0, 1)
    y[..., 2] = np.clip(y[..., 2] * 0.97, 0, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write('TITLE "synthetic film"\nLUT_3D_SIZE %d\n' % n)
        for v in y.reshape(-1, 3):
            f.write("%.6f %.6f %.6f\n" % tuple(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "fixtures"))
    args = ap.parse_args()
    out = Path(args.out)
    (out / "luts").mkdir(parents=True, exist_ok=True)
    (out / "bad").mkdir(parents=True, exist_ok=True)

    cc = load_mod("cc", REPO / "scripts" / "lut-to-ccprofile.py")

    # ① 合成 LUT
    lut_path = out / "luts" / "portra_like.cube"
    synth_lut(lut_path, 33)
    print(f"✓ {lut_path}")

    # ② 坏样本 A：缺护高光（空间/基底声明都正确）
    import uuid
    cal = load_mod("cal", REPO / "scripts" / "calibrate-luts.py")
    lut_arr, _ = cc.core.load_lut(str(lut_path))
    gain, info = cal.calibrate(lut_arr, "brightness", 0.0)          # 与生成时同口径标定
    print(f"   （缺护高光样本用标定 gain={gain:.4f}：中灰 {info['mid_out_before']} → {info['mid_out_after']}）")
    colors = cc.build_table(lut_path, 32, "display", float(gain), 0.0)
    blob = cc.encode_table(colors, 32, cc.META["display"])
    tid, lid = cc.table_id(blob), uuid.uuid4().hex.upper()
    (out / "bad" / "portra_noprotect.xmp").write_text(
        cc.look_xmp("Synthetic (no highlight protection)", tid, cc.b85_encode(blob),
                    "Adobe Standard", "", lid,
                    "评测样本：空间/元数据正确，但表格未做护高光"),
        encoding="utf-8")
    print(f"✓ {out/'bad/portra_noprotect.xmp'}")

    # ③ 坏样本 B：空间错配（线性域的表 + 显示域的元数据声明）
    colors = cc.build_table(lut_path, 32, "linear", 0.3472, 0.0)
    blob = cc.encode_table(colors, 32, cc.META["display"])          # ← 故意配错
    tid, lid = cc.table_id(blob), uuid.uuid4().hex.upper()
    (out / "bad" / "portra_spacemismatch.xmp").write_text(
        cc.look_xmp("Synthetic (space mismatch)", tid, cc.b85_encode(blob),
                    "Adobe Standard", "", lid,
                    "评测样本：表格按线性族烘制，却按显示域声明"),
        encoding="utf-8")
    print(f"✓ {out/'bad/portra_spacemismatch.xmp'}")

    # ④ 自检：两个坏样本的签名必须可区分
    def white_and_mid(p: Path):
        import re
        s = p.read_text(encoding="utf-8")
        t = re.search(r'crs:RGBTable="([0-9A-F]+)"', s).group(1)
        tbl, _ = cc.decode_table(re.search(r'crs:Table_' + t + r'="([^"]+)"', s).group(1))
        ramp = np.repeat(np.linspace(0, 1, 256)[:, None], 3, axis=1)[None].astype(np.float32)
        o = cc.core._apply_3d(tbl.astype(np.float32), ramp)[0].mean(1) * 255
        return float(o[128]), float(o[255])

    m1, w1 = white_and_mid(out / "bad" / "portra_noprotect.xmp")
    m2, w2 = white_and_mid(out / "bad" / "portra_spacemismatch.xmp")
    print(f"\n签名对照：缺护高光 中灰 {m1:.1f} / 纯白 {w1:.1f}；空间错配 中灰 {m2:.1f} / 纯白 {w2:.1f}")
    ok = (118 <= m1 <= 165 and w1 <= 220 and w2 <= 200)
    print("样本可用于评测:", "✅" if ok else "❌（签名不符合预期，检查生成参数）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
