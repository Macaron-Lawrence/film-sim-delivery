#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 跨平台自检：造 LUT → 标定 → 转 Adobe RGBTable → 解回比对 + 护高光断言。

  python3 scripts/selftest.py                    # 在临时目录里跑（不动你的素材）
  python3 scripts/selftest.py --work /tmp/xx

`selftest.sh` 是它的 POSIX 包装，二者等价；Windows 原生环境直接用这个。
退出码 0 = 通过。
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
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def load_cc():
    spec = importlib.util.spec_from_file_location("cc", HERE / "lut-to-ccprofile.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="")
    args = ap.parse_args()

    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="filmsim-selftest-"))
    luts = work / "luts"
    luts.mkdir(parents=True, exist_ok=True)
    print(f"== film-sim-delivery 自检（{work}）==")

    # ① 造一张形状像真胶片的测试 LUT：抬暗部、压高光、轻微暖调
    N = 17
    r, g, b = np.meshgrid(*[np.linspace(0, 1, N)] * 3, indexing="ij")
    rgb = np.transpose(np.stack([r, g, b], -1), (2, 1, 0, 3))     # [b][g][r] = .cube 顺序
    y = rgb ** 1.05
    y[..., 0] = np.clip(y[..., 0] * 1.02, 0, 1)
    y[..., 2] = np.clip(y[..., 2] * 0.98, 0, 1)
    y = np.clip(y * 0.9 + 0.03, 0, 1)
    cube = luts / "selftest_look.cube"
    with open(cube, "w", encoding="utf-8") as f:
        f.write(f'TITLE "selftest"\nLUT_3D_SIZE {N}\n')
        for v in y.reshape(-1, 3):
            f.write("%.6f %.6f %.6f\n" % tuple(v))
    print(f"  ✓ 造出测试 LUT：{cube}")

    # ② 标定（参数必须与 ③ 的生成参数一致：brightness + protect 0.68）
    py = sys.executable
    cal = luts / "_calibration.json"
    subprocess.run([py, str(HERE / "calibrate-luts.py"), "--dir", str(luts),
                    "--mode", "brightness", "--protect", "0.68", "--out", str(cal)],
                   check=True, stdout=subprocess.DEVNULL)
    print("  ✓ 标定完成")

    # ③ 生成创意配置文件
    out = work / "lr-ccprofiles"
    subprocess.run([py, str(HERE / "lut-to-ccprofile.py"), "--dir", str(luts),
                    "--calibration", str(cal), "--out", str(out),
                    "--space", "display", "--protect", "0.68",
                    "--allow-unknown", "--label", "自检"],
                   check=True, stdout=subprocess.DEVNULL)
    print("  ✓ 生成创意配置文件")

    # ④ 解回比对 + 护高光断言
    cc = load_cc()
    profiles = [p for p in out.glob("*.xmp") if "wrapper" not in p.name]
    assert profiles, "没有生成配置文件"
    import json
    import re
    import zlib
    import struct
    txt = profiles[0].read_text(encoding="utf-8")
    tid = re.search(r'crs:RGBTable="([0-9A-Fa-f]+)"', txt).group(1)
    payload = re.search(r'crs:Table_' + tid + r'="([^"]+)"', txt).group(1)
    table, div = cc.decode_table(payload)

    import hashlib
    data = zlib.decompress(cc.b85_decode(payload)[4:])
    print(f"  · 表 ID = MD5(表内容)：{'✓' if hashlib.md5(data).hexdigest().upper() == tid.upper() else '✗'}")

    gain = json.loads(cal.read_text(encoding="utf-8"))["selftest_look"]["pre_gain"]
    want = cc.build_table(cube, div, "display", gain, 0.68)
    err = float(np.abs(table - want).max()) * 65535
    print(f"  · 解回比对：最大误差 {err:.2f}/65535（阈值 1.0）")

    lut, _ = cc.core.load_lut(str(cube))          # LUT 读取/施加在 lr-filmsim.py（作为 cc.core 暴露）
    inp = np.repeat(np.linspace(0, 1, 256)[:, None], 3, axis=1)[None].astype(np.float32)
    base = cc.core.apply_lut(inp, lut, None, 1.0, False, gain)
    lum = inp.mean(-1)
    t = np.clip((lum - 0.68) / 0.32, 0, 1)
    w = 1 - (t * t * (3 - 2 * t))
    o = base * w[..., None] + inp * (1 - w[..., None])
    white, mid = float(o[0, -1].mean()) * 255, float(o[0, 128].mean()) * 255
    print(f"  · 护高光：输入 255 → {white:.1f}（要求 ≥250）；中灰 128 → {mid:.1f}（要求 118–145）")

    ok = err <= 1.0 and white >= 250 and 118 <= mid <= 145
    print("自检结果:", "✅ 通过" if ok else "❌ 未通过")
    if ok and not args.work:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
