#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
curate-rt-halclut.py —— 从 RawTherapee Film Simulation Collection（295 个 HaldCLUT）里
挑出经典卷，复制成干净文件名放进 <root>/luts/rt/，供校准 + 转 Lightroom 创意配置文件。

许可：该集合为 CC BY-SA 4.0（见其 README.txt），署名 Pat David / Pavlov Dmitry / Michael Ezra。
用法：
  python3 scripts/curate-rt-halclut.py            # 复制精选（约 30 个）
  python3 scripts/curate-rt-halclut.py --all      # 复制全部 295 个
  python3 scripts/curate-rt-halclut.py --list     # 只看清单
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

import os

import argparse
import shutil
from pathlib import Path

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
SRC = PROJ / "数据" / "halclut" / "HaldCLUT"
DST = PROJ / "数据" / "luts" / "rt"

# 精选：label → 集合内的相对路径
CURATED: dict[str, str] = {
    # —— 柯达彩色 ——
    "rt_ektar100":          "Color/Kodak/Kodak Ektar 100.png",
    "rt_portra160":         "Color/Kodak/Kodak Portra 160 2.png",
    "rt_portra400":         "Color/Kodak/Kodak Portra 400 2.png",
    "rt_portra400vc":       "Color/Kodak/Kodak Portra 400 VC 2.png",
    "rt_portra800":         "Color/Kodak/Kodak Portra 800 2.png",
    "rt_kodachrome64":      "Color/Kodak/Kodak Kodachrome 64.png",
    "rt_kodachrome25":      "Color/Kodak/Kodak Kodachrome 25.png",
    "rt_ektachrome100vs":   "Color/Kodak/Kodak Ektachrome 100 VS.png",
    "rt_elitechrome200":    "Color/Kodak/Kodak Elite Chrome 200.png",
    "rt_eliteextracolor100": "Color/Kodak/Kodak Elite ExtraColor 100.png",
    # —— 富士彩色 ——
    "rt_velvia50":          "Color/Fuji/Fuji Velvia 50.png",
    "rt_provia100f":        "Color/Fuji/Fuji Provia 100F.png",
    "rt_astia100f":         "Color/Fuji/Fuji Astia 100F.png",
    "rt_fuji160c":          "Color/Fuji/Fuji 160C 2.png",
    "rt_fuji400h":          "Color/Fuji/Fuji 400H 2.png",
    "rt_fuji800z":          "Color/Fuji/Fuji 800Z 2.png",
    "rt_superia_reala":     "Color/Fuji/Fuji Superia Reala 100.png",
    "rt_superia400":        "Color/Fuji/Fuji Superia 400 2.png",
    "rt_sensia100":         "Color/Fuji/Fuji Sensia 100.png",
    "rt_fp100c":            "Color/Fuji/Fuji FP-100c 3.png",
    # —— 其他彩色 ——
    "rt_agfa_vista200":     "Color/Agfa/Agfa Vista 200.png",
    "rt_agfa_ultra100":     "Color/Agfa/Agfa Ultra Color 100.png",
    "rt_agfa_precisa100":   "Color/Agfa/Agfa Precisa 100.png",
    "rt_polaroid690":       "Color/Polaroid/Polaroid 690 3.png",
    # —— 黑白：柯达 ——
    "rt_trix400":           "Black-and-White/Kodak/Kodak TRI-X 400 2.png",
    "rt_tmax100":           "Black-and-White/Kodak/Kodak T-Max 100.png",
    "rt_tmax400":           "Black-and-White/Kodak/Kodak T-Max 400.png",
    "rt_tmax3200":          "Black-and-White/Kodak/Kodak TMAX 3200 2.png",
    "rt_hie_infra":         "Black-and-White/Kodak/Kodak HIE (HS Infra).png",
    "rt_bw400cn":           "Black-and-White/Kodak/Kodak BW 400 CN.png",
    # —— 黑白：依尔福 ——
    "rt_hp5":               "Black-and-White/Ilford/Ilford HP5 2.png",
    "rt_delta100":          "Black-and-White/Ilford/Ilford Delta 100.png",
    "rt_delta3200":         "Black-and-White/Ilford/Ilford Delta 3200 2.png",
    "rt_fp4":               "Black-and-White/Ilford/Ilford FP4 Plus 125.png",
    "rt_panf50":            "Black-and-White/Ilford/Ilford Pan F Plus 50.png",
    "rt_xp2":               "Black-and-White/Ilford/Ilford XP2.png",
    # —— 黑白：富士 / 爱克发 / 禄来 ——
    "rt_acros100":          "Black-and-White/Fuji/Fuji Neopan Acros 100.png",
    "rt_neopan1600":        "Black-and-White/Fuji/Fuji Neopan 1600 2.png",
    "rt_apx100":            "Black-and-White/Agfa/Agfa APX 100.png",
    "rt_apx25":             "Black-and-White/Agfa/Agfa APX 25.png",
    "rt_rollei_ortho25":    "Black-and-White/Rollei/Rollei Ortho 25.png",
    "rt_rollei_retro80s":   "Black-and-White/Rollei/Rollei Retro 80s.png",
    "rt_rollei_ir400":      "Black-and-White/Rollei/Rollei IR 400.png",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="从 RT HaldCLUT 集合挑经典卷")
    ap.add_argument("--src", default=str(SRC), help="HaldCLUT 集合目录（解压后的 HaldCLUT/）")
    ap.add_argument("--dst", default=str(DST), help="输出目录（默认 <root>/luts/rt）")
    ap.add_argument("--all", action="store_true", help="复制全部 295 个")
    ap.add_argument("--list", action="store_true", help="只列清单，不复制")
    args = ap.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    if not src_dir.exists():
        print(f"找不到集合：{src_dir}")
        print("先拉取： bash scripts/fetch_sources.sh rt   （默认落在 <root>/sources/HaldCLUT）")
        print("然后：   python3 scripts/curate-rt-halclut.py --src <root>/sources/HaldCLUT")
        return 2

    if args.all:
        files = {f"rt_{p.parent.name.lower()}_{p.stem.lower().replace(' ', '_').replace('.', '')}": str(p.relative_to(src_dir))
                 for p in sorted(src_dir.rglob("*.png")) if p.name != "Hald_CLUT_Identity_12.tif"}
    else:
        files = CURATED

    dst_dir.mkdir(parents=True, exist_ok=True)
    ok = miss = 0
    for label, rel in files.items():
        src = src_dir / rel
        if not src.exists():
            print(f"✗ 找不到 {rel}")
            miss += 1
            continue
        dst = dst_dir / f"{label}.png"
        if not args.list:
            shutil.copy2(src, dst)
        ok += 1
    print(f"{'将复制' if args.list else '已复制'} {ok} 个（缺失 {miss}）→ {dst_dir}")
    if miss:
        print("缺失的多半是文件名后缀（+/-）写法差异，用 --list 对照集合里的实际名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
