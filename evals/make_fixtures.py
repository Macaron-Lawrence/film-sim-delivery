#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fixtures.py —— 生成评测样本（可复现，不依赖任何上游 LUT 数据）。

评测用的是**合成**的胶片 LUT 与两个"坏样本"，所以仓库里不需要放任何第三方 LUT，
也不用担心上游许可。跑一次这个脚本，就能在 evals/fixtures/ 下得到：

  luts/portra_like.cube            合成胶片 LUT（暖调 + 抬暗部 + 压高光），33³
  bad/portra_noprotect.xmp         空间/元数据都对，但 **没有护高光** → 纯白封顶 ~217
  bad/portra_spacemismatch.xmp     按线性族烘的表格，却按显示域声明 → 整张发灰

用法：
  python3 evals/make_fixtures.py                        # 写进 evals/fixtures/
  python3 evals/make_fixtures.py --out /tmp/fx          # 写到别处
  python3 evals/make_fixtures.py --verify-reproducible  # 生成两次比对哈希（CI 用）

生成是**字节可复现**的：不写时间戳、UUID 由表格 ID 派生。退出码 0 = 通过。
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
import hashlib
import importlib.util
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# 两个坏样本的中间灰 / 纯白签名必须落在这个区间里，否则样本就失去评测价值
SIG_NOPROTECT = dict(mid=(118, 165), white=(0, 220))
SIG_MISMATCH = dict(mid=(0, 118), white=(0, 200))


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
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('TITLE "synthetic film"\nLUT_3D_SIZE %d\n' % n)
        for v in y.reshape(-1, 3):
            f.write("%.6f %.6f %.6f\n" % tuple(v))


def stable_uuid(*parts: str) -> str:
    """由内容派生的 32 位十六进制 ID —— 取代 uuid4()，让样本字节可复现。"""
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest().upper()


def write_lf(path: Path, text: str) -> None:
    """按 LF 写文件。注意不能用 Path.write_text(newline=...)：那是 Python 3.10+ 才有的参数，
    在 3.9 上直接 TypeError（CI 的 3.9 格子就是这么红的）。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def white_and_mid(cc, path: Path):
    """独立解回一个 XMP：返回 (中灰, 纯白) 的 0-255 响应。"""
    s = path.read_text(encoding="utf-8")
    t = re.search(r'crs:RGBTable="([0-9A-F]+)"', s).group(1)
    tbl, _ = cc.decode_table(re.search(r'crs:Table_' + t + r'="([^"]+)"', s).group(1))
    ramp = np.repeat(np.linspace(0, 1, 256)[:, None], 3, axis=1)[None].astype(np.float32)
    o = cc.core._apply_3d(tbl.astype(np.float32), ramp)[0].mean(1) * 255
    return float(o[128]), float(o[255])


def generate(out: Path, quiet: bool = False) -> dict:
    """把三类样本写进 out/，返回签名结果。"""
    def say(*a):
        if not quiet:
            print(*a)

    (out / "luts").mkdir(parents=True, exist_ok=True)
    (out / "bad").mkdir(parents=True, exist_ok=True)

    cc = load_mod("cc", REPO / "scripts" / "lut-to-ccprofile.py")
    cal = load_mod("cal", REPO / "scripts" / "calibrate-luts.py")

    # ① 合成 LUT
    lut_path = out / "luts" / "portra_like.cube"
    synth_lut(lut_path, 33)
    say(f"✓ {lut_path}")

    lut_arr, _ = cc.core.load_lut(str(lut_path))

    # ② 坏样本 A：缺护高光（空间/基底声明都正确）
    gain, info = cal.calibrate(lut_arr, "brightness", 0.0)          # 与生成时同口径标定
    say(f"   （缺护高光样本用标定 gain={gain:.4f}：中灰 {info['mid_out_before']} → {info['mid_out_after']}）")
    colors = cc.build_table(lut_path, 32, "display", float(gain), 0.0)
    blob = cc.encode_table(colors, 32, cc.META["display"])
    tid = cc.table_id(blob)
    write_lf(out / "bad" / "portra_noprotect.xmp",
             cc.look_xmp("Synthetic (no highlight protection)", tid, cc.b85_encode(blob),
                         "Adobe Standard", "", stable_uuid("noprotect", tid),
                         "评测样本：空间/元数据正确，但表格未做护高光"))
    say(f"✓ {out/'bad/portra_noprotect.xmp'}")

    # ③ 坏样本 B：空间错配（线性域的表 + 显示域的元数据声明）
    colors = cc.build_table(lut_path, 32, "linear", 0.3472, 0.0)
    blob = cc.encode_table(colors, 32, cc.META["display"])          # ← 故意配错
    tid = cc.table_id(blob)
    write_lf(out / "bad" / "portra_spacemismatch.xmp",
             cc.look_xmp("Synthetic (space mismatch)", tid, cc.b85_encode(blob),
                         "Adobe Standard", "", stable_uuid("mismatch", tid),
                         "评测样本：表格按线性族烘制，却按显示域声明"))
    say(f"✓ {out/'bad/portra_spacemismatch.xmp'}")

    # ④ 签名：两个坏样本必须可区分，且落在预期区间
    m1, w1 = white_and_mid(cc, out / "bad" / "portra_noprotect.xmp")
    m2, w2 = white_and_mid(cc, out / "bad" / "portra_spacemismatch.xmp")
    say(f"\n签名对照：缺护高光 中灰 {m1:.1f} / 纯白 {w1:.1f}；空间错配 中灰 {m2:.1f} / 纯白 {w2:.1f}")
    ok = (SIG_NOPROTECT["mid"][0] <= m1 <= SIG_NOPROTECT["mid"][1]
          and SIG_NOPROTECT["white"][0] <= w1 <= SIG_NOPROTECT["white"][1]
          and SIG_MISMATCH["mid"][0] <= m2 <= SIG_MISMATCH["mid"][1]
          and SIG_MISMATCH["white"][0] <= w2 <= SIG_MISMATCH["white"][1])
    return {"ok": ok, "noprotect": (m1, w1), "mismatch": (m2, w2)}


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "fixtures"))
    ap.add_argument("--verify-reproducible", action="store_true",
                    help="生成两遍并比对哈希（CI 用；不写 --out）")
    args = ap.parse_args()

    if args.verify_reproducible:
        d1 = Path(tempfile.mkdtemp(prefix="filmsim-fx-a-"))
        d2 = Path(tempfile.mkdtemp(prefix="filmsim-fx-b-"))
        try:
            r1 = generate(d1, quiet=True)
            r2 = generate(d2, quiet=True)
            h1, h2 = tree_hash(d1), tree_hash(d2)
            print(f"  第一遍 {h1[:16]}  第二遍 {h2[:16]}")
            same = h1 == h2
            print("字节可复现:", "✅ 两次生成完全一致" if same else "❌ 两次生成不同")
            return 0 if (same and r1["ok"] and r2["ok"]) else 1
        finally:
            shutil.rmtree(d1, ignore_errors=True)
            shutil.rmtree(d2, ignore_errors=True)

    res = generate(Path(args.out))
    print("样本可用于评测:", "✅" if res["ok"] else "❌（签名不符合预期，检查生成参数）")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
