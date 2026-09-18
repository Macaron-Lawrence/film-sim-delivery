#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bake-spectral-luts.py —— 用 spectral_film_lut（MIT）烘 spektrafilm 缺的卷。

补的缺口：黑白（Tri-X / Double-X）、正片（Velvia 50 / Provia / Kodachrome / Ektachrome /
Aerochrome 红外伪彩 / Instax / FP-100C）、电影卷配印片（Vision3 × 2383 / Technicolor）。

必须在 数据/.venv-spectral 的 Python 3.13 下运行（该包要求 ≥3.11）：
  python3 scripts/bake-spectral-luts.py --list
  python3 scripts/bake-spectral-luts.py                # 按内置清单烘
  python3 scripts/bake-spectral-luts.py --only trix velvia

输出的 .cube 一律按 **sRGB 编码输入 → sRGB 编码输出**（与 spektrafilm 那批一致），
这样可以直接喂给 scripts/lut-to-ccprofile.py 做成 Lightroom 创意配置文件。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
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

# 内置烘制清单：label → (胶片名, 印片名 或 None)
#   None = 正片直接观看（幻灯片），或黑白只用底片
JOBS: dict[str, tuple[str, str | None]] = {
    # —— 正片 / 幻灯片（spektrafilm 命令行做不了，正好补上）——
    "velvia50":          ("Fuji Velvia 50", None),
    "provia100f":        ("Fuji Provia 100F", None),
    "kodachrome64":      ("Kodachrome 64", None),
    "ektachrome100d":    ("Kodak Ektachrome 100D", None),
    "aerochrome":        ("Kodak Aerochrome III Infrared Film 1443", None),
    "instax":            ("Fuji Instax color", None),
    "fp100c":            ("Fuji FP-100C", None),
    # —— 黑白（底片 × 黑白相纸）——
    "trix400":           ("Kodak Tri-X 400", "Kodak 2302"),
    "trix400_dev7":      ("Kodak Trix-X 400 Dev 7", "Kodak 2302"),
    "doublex5222":       ("Kodak 5222", "Kodak 2302"),
    "doublex5222_dev9":  ("Kodak 5222 Dev 9", "Kodak 2302"),
    "trix_polymax":      ("Kodak Tri-X 400", "Kodak Polymax Fine-Art Paper Grade 2"),
    # —— 电影：负片 × 印片 ——
    "vision3_250d_2383": ("Kodak Vision3 250D 5207", "Kodak Vision 2383"),
    "vision3_500t_2383": ("Kodak Vision3 500T 5219", "Kodak Vision 2383"),
    "vision3_50d_2383":  ("Kodak Vision3 50D 5203", "Kodak Vision 2383"),
    "vision3_250d_2393": ("Kodak Vision3 250D 5207", "Kodak Vision Premier 2393"),
    "technicolor_v":     ("Kodak 5247", "Technicolor V"),
    "eterna_3513di":     ("Fuji Eterna 500", "Fuji Eterna-CP Type 3513DI"),
    "eterna_vivid_3513": ("Fuji Eterna 500 Vivid", "Fuji Eterna-CP Type 3513DI"),
    # —— 经典负片：与 spektrafilm 版本对照 ——
    "ektar100_sfl":      ("Kodak Ektar 100", "Kodak Portra Endura Paper"),
    "portra400_sfl":     ("Kodak Portra 400", "Kodak Portra Endura Paper"),
    "gold200_sfl":       ("Kodak Gold 200", "Kodak Portra Endura Paper"),
    "portra400_fuji":    ("Kodak Portra 400", "Fuji Crystal Archive Super Type C"),
    "superia_reala":     ("Fuji Superia Reala", "Fuji Crystal Archive Super Type C"),
    "natura1600":        ("Fuji Natura 1600", "Fuji Crystal Archive Super Type C"),
    "aerocolor":         ("Kodak Aerocolor IV 2460", "Kodak Endura Premier Paper"),
    "vericolor_iii":     ("Kodak Vericolor III", "Kodak Supra Endura Paper"),
    "agfa_vista100":     ("Agfa Vista 100", "Fuji Crystal Archive Super Type C"),
}


def load_stocks():
    from spectral_film_lut import FILM_STOCKS
    from spectral_film_lut.film_spectral import FilmSpectral

    out = {}
    for stock in FILM_STOCKS:
        try:
            fs = FilmSpectral(stock)
            out[fs.name] = fs
        except Exception as exc:  # noqa: BLE001
            print(f"  （跳过 {getattr(stock, 'name', stock)}: {exc}）", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="用 spectral_film_lut 烘缺口卷的 .cube")
    ap.add_argument("--out", default=str(default_luts() / "spectral"))
    ap.add_argument("--size", type=int, default=33)
    ap.add_argument("--only", nargs="*", default=None, help="只烘这些 label（模糊匹配）")
    ap.add_argument("--list", action="store_true", help="列出所有可用卷名后退出")
    ap.add_argument("--noise", action="store_true", help="顺带导出一份胶片颗粒叠加 PNG")
    args = ap.parse_args()

    t0 = time.time()
    print("加载卷数据（首次约需几十秒）…")
    stocks = load_stocks()
    print(f"  载入 {len(stocks)} 个卷（{time.time()-t0:.0f}s）")

    if args.list:
        print("\n可用卷名（直接抄进 JOBS 或 --only）：")
        for n in sorted(stocks):
            s = stocks[n]
            kind = f"{getattr(s, 'film_type', '?')}/{getattr(s, 'stage', '?')}"
            print(f"  {n:34s} {kind}")
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    from spectral_film_lut.utils import create_lut

    jobs = JOBS
    if args.only:
        jobs = {k: v for k, v in JOBS.items() if any(o.lower() in k.lower() for o in args.only)}
    missing = [k for k, (neg, pr) in jobs.items() if neg not in stocks or (pr and pr not in stocks)]
    if missing:
        print("\n⚠️ 下列任务找不到对应卷名，用 --list 查证后修 JOBS：")
        for k in missing:
            neg, pr = jobs[k]
            print(f"   {k}: 负片={neg!r}{'' if neg in stocks else ' ✗'}  印片={pr!r}"
                  f"{'' if (pr is None or pr in stocks) else ' ✗'}")

    cwd = os.getcwd()
    os.chdir(out_dir)
    ok = 0
    try:
        for label, (neg, pr) in jobs.items():
            if neg not in stocks or (pr and pr not in stocks):
                continue
            t = time.time()
            try:
                create_lut(
                    stocks[neg],
                    stocks[pr] if pr else None,
                    lut_size=args.size,
                    name=label,
                    cube=True,
                    input_colorspace="sRGB",
                    output_gamut="Rec. 709",
                    gamma_func="sRGB",
                    verbose=False,
                )
                ok += 1
                print(f"✓ {label:20s} {neg:22s} × {str(pr or '—'):24s} {time.time()-t:5.1f}s")
            except Exception as exc:  # noqa: BLE001
                print(f"✗ {label:20s} 失败：{type(exc).__name__}: {exc}")
    finally:
        os.chdir(cwd)

    print(f"\n完成 {ok}/{len(jobs)} → {out_dir}（共 {time.time()-t0:.0f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
