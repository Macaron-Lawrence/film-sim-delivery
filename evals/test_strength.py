#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_strength.py —— 强度（Amount）功能的回归测试。

强度有三条实现路径，这个测试锁住它们的关键性质：

  A. 烘焙强度  --bake-strength s   → 表本身降级，不依赖宿主滑块
     必须严格等于 out = s·(100% 表) + (1-s)·输入恒等（否则"50%"名不副实）
  B. 多强度预设 --amounts 1,0.75,0.5 → 多个 wrapper 共用**同一张表**（不重复 76KB×N）
  C. --supports-amount            → 声明 SupportsAmount2=True（尝试启用宿主滑块）

另外锁住直接套图路径的 --strength 与 A 的语义一致（都是跟输入线性混合）。

用法： python3 evals/test_strength.py
"""
from __future__ import annotations

from pathlib import Path  # noqa: F401

import glob
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
FIXTURES = HERE / "fixtures"
PY = sys.executable
RESULTS = []


def check(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append((name, bool(ok), note))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  —— {note}" if note else ""))


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *[str(a) for a in args]], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def first_table(folder: Path):
    """取目录里第一个**配置文件**的解码表（跳过 wrapper）。"""
    for f in sorted(glob.glob(str(folder / "*.xmp"))):
        s = Path(f).read_text(encoding="utf-8")
        m = re.search(r'crs:RGBTable="([0-9A-Fa-f]+)"', s)
        if not m:
            continue
        payload = re.search(r'crs:Table_' + m.group(1) + r'="([^"]+)"', s).group(1)
        pay = cc.decode_table(payload)[0]
        return pay, Path(f)
    raise AssertionError(f"{folder} 里没有配置文件")


cc = load("cc", SCRIPTS / "lut-to-ccprofile.py")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="filmsim-strength-"))
    luts = work / "luts"
    luts.mkdir()
    shutil.copy2(FIXTURES / "luts/portra_like.cube", luts / "portra_like.cube")
    cal = luts / "cal.json"
    r = run(SCRIPTS / "calibrate-luts.py", "--dir", luts, "--mode", "brightness",
            "--protect", "0.68", "--out", cal)
    if r.returncode != 0:
        print("标定失败：", r.stdout[-400:], r.stderr[-400:])
        return 1

    common = ["--dir", luts, "--space", "display", "--calibration", cal,
              "--mode", "brightness", "--protect", "0.68"]

    # ── A. 烘焙强度必须真的等于 s·LUT + (1−s)·输入 ─────────────────────
    full, half = work / "full", work / "half"
    r1 = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", full)
    r2 = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", half,
             "--bake-strength", "0.5", "--label", "强度50")
    if r1.returncode or r2.returncode:
        check("烘焙强度：两档都能生成", False, f"{r1.returncode}/{r2.returncode}")
    else:
        t100, _ = first_table(full)
        t50, _ = first_table(half)
        div = t100.shape[0]
        ax = np.linspace(0, 1, div, dtype=np.float32)
        ri, gi, bi = np.meshgrid(ax, ax, ax, indexing="ij")
        identity = np.stack([ri, gi, bi], -1).reshape(div, div, div, 3)
        want = t100 * 0.5 + identity * 0.5
        err = float(np.abs(t50 - want).max() * 65535)
        check("烘焙 50% == 0.5·(100%) + 0.5·输入（数值等价）", err <= 1.0,
              f"最大差 {err:.3f}/65535")
        # 强度必须真的变了（防止"等价"退化成恒等或不变）
        mid = (div // 2,) * 3
        d_mid = abs(float(t100[mid].mean()) - float(t50[mid].mean())) * 255
        check("50% 与 100% 确实不同（强度真的生效）", d_mid > 0.5, f"中灰相差 {d_mid:.2f}/255")
        check("纯白仍回到 255（护高光在降强度后依然成立）",
              abs(float(t50[(div - 1,) * 3].mean()) * 255 - 255.0) < 1.0,
              f"{float(t50[(div - 1,) * 3].mean()) * 255:.1f}")

    r = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", work / "bad",
            "--bake-strength", "0")
    check("--bake-strength 0 被拒（0 等于不用这张 LUT）", r.returncode != 0,
          f"退出码={r.returncode}")

    # ── B. 多强度预设共用同一张表 ──────────────────────────────────────
    multi = work / "multi"
    r = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", multi,
            "--amounts", "1,0.75,0.5,0.25")
    if r.returncode != 0:
        check("多强度预设：生成成功", False, r.stderr[-200:])
    else:
        wraps = sorted(multi.glob("*wrapper.xmp"))
        profiles = [p for p in sorted(multi.glob("*.xmp")) if "wrapper" not in p.name]
        amts = []
        uuids = set()
        for w in wraps:
            s = w.read_text(encoding="utf-8")
            amts.append(re.search(r'crs:Amount="([^"]+)"', s).group(1))
            uuids.add(re.search(r'crs:UUID="([^"]+)"', s).group(1))
        check("生成 4 个强度预设 + 1 个配置文件",
              len(wraps) == 4 and len(profiles) == 1,
              f"wrapper={len(wraps)} profile={len(profiles)}")
        check("四个预设的 crs:Amount 分别为 1/0.75/0.5/0.25",
              sorted(amts, key=float) == ["0.25", "0.5", "0.75", "1"],
              f"{sorted(amts, key=float)}")
        # 关键：所有 wrapper 指向同一个 Look 实体 → 表只有一份
        looks = {re.search(r'crs:Look\s+crs:Name="[^"]*"\s+crs:Amount="[^"]*"\s+crs:UUID="([^"]+)"',
                           w.read_text(encoding="utf-8")).group(1) for w in wraps}
        check("四个预设共用同一个 Look UUID（表不重复）", len(looks) == 1, f"{len(looks)} 个不同 UUID")
        check("只有配置文件里带表数据（wrapper 不含 RGBTable）",
              all("crs:RGBTable" not in w.read_text(encoding="utf-8") for w in wraps),
              "wrapper 无表")
        total = sum(p.stat().st_size for p in multi.glob("*.xmp"))
        one = profiles[0].stat().st_size
        check("总体积 ≈ 1 张表 + 4 个小预设（未按强度复制表）",
              total < one * 1.3, f"合计 {total/1024:.0f}KB vs 单表 {one/1024:.0f}KB")

    r = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", work / "bad2",
            "--amounts", "1,1.5")
    check("--amounts 越界值被拒", r.returncode != 0, f"退出码={r.returncode}")

    # ── C. SupportsAmount 声明 ────────────────────────────────────────
    slid = work / "slider"
    r = run(SCRIPTS / "lut-to-ccprofile.py", *common, "--out", slid, "--supports-amount")
    if r.returncode == 0:
        s = (sorted(slid.glob("*wrapper.xmp"))[0]).read_text(encoding="utf-8")
        check("--supports-amount → 预设层声明 SupportsAmount2=True",
              'crs:SupportsAmount2="True"' in s and 'crs:SupportsAmount="True"' in s,
              "两处声明均为 True")
        d = (sorted(p for p in slid.glob("*.xmp") if "wrapper" not in p.name)[0]).read_text(encoding="utf-8")
        check("--supports-amount 不误改 Look 配置文件本身",
              'crs:SupportsAmount="False"' in d, "Look 仍为 False（与官方一致）")

    # ── D. 直接套图路径的 --strength 语义一致 ─────────────────────────
    src = FIXTURES / "photos/highlight_test.png"
    if src.exists():
        out0, out5 = work / "s0", work / "s5"
        a = run(SCRIPTS / "lr-filmsim.py", "--lut", luts / "portra_like.cube",
                "--out", out0, "--strength", "1.0", "--pre-gain", "1.518", src)
        b = run(SCRIPTS / "lr-filmsim.py", "--lut", luts / "portra_like.cube",
                "--out", out5, "--strength", "0.5", "--pre-gain", "1.518", src)
        if a.returncode == 0 and b.returncode == 0:
            from PIL import Image
            ia = np.asarray(Image.open(next(out0.glob("*.png"))).convert("RGB"), dtype=np.float32)
            ib = np.asarray(Image.open(next(out5.glob("*.png"))).convert("RGB"), dtype=np.float32)
            orig = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
            want = ia * 0.5 + orig * 0.5
            err = float(np.abs(ib - want).max())
            check("直接套图 --strength 0.5 == 0.5·输出 + 0.5·原图", err <= 1.0,
                  f"最大差 {err:.2f}/255")
        else:
            check("直接套图 --strength 能跑", False, f"{a.returncode}/{b.returncode}")

    shutil.rmtree(work, ignore_errors=True)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n强度功能回归：{passed}/{len(RESULTS)} 通过")
    for name, ok, note in RESULTS:
        if not ok:
            print(f"  ✗ {name}  {note}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
