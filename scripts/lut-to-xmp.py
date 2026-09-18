#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lut-to-xmp.py —— 把 spektrafilm 的 .cube 胶片 LUT 转成 Lightroom 可用的 XMP 预设。

⚠️ 这是**近似**：Lightroom Classic 不支持 3D LUT，预设里只能放
   色调曲线 + 颜色分级 + HSL 分色 + 颗粒/暗角 这些参数。
   本脚本从 LUT 里反解出这些参数：
     * 三条通道曲线：取自中性灰轴（LUT 对灰阶的 R/G/B 响应）
     * 8 个色相带的 色相/饱和度/明度 偏移：从色相环采样反解
     * 全局 饱和度/鲜艳度：从彩度响应反解
     * 三段颜色分级（阴影/中间调/高光）：从中性色偏反解
     * 颗粒 / 暗角 / 锐化：按胶片的"味道"预设表
   本脚本产出的是参数化近似，不是编码后的 3D LUT；仓库没有可复现的保真度评分方法，
   因此不提供保真度百分比。要保留跨通道色相扭转请走 LUT 路线（ART / 外部编辑器 / 命令行套 LUT）。

用法：
  python3 scripts/lut-to-xmp.py                 # 转换 <root>/luts/*.cube
  python3 scripts/lut-to-xmp.py --only portra ektar
  python3 scripts/lut-to-xmp.py --out 数据/lr-presets
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
import uuid
from pathlib import Path

import numpy as np
import sys

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

PRE_GAIN = 0.3472          # = 1/2.88，抵掉 spektrafilm 的 +4 档曝光定位
CURVE_POINTS = 11

# Lightroom 的 8 个色相带（中心角度）
BANDS = [("Red", 0), ("Orange", 30), ("Yellow", 60), ("Green", 120),
         ("Aqua", 180), ("Blue", 240), ("Purple", 280), ("Magenta", 320)]

# 每个胶片的"味道"：(显示名, 颗粒量, 颗粒大小, 颗粒粗糙度, 暗角强度)
TASTE = {
    "portra400":   ("柯达 Portra 400",   22, 26, 42, 10),
    "portra160":   ("柯达 Portra 160",   18, 22, 45, 10),
    "portra800":   ("柯达 Portra 800",   32, 34, 38, 12),
    "ektar100":    ("柯达 Ektar 100",    16, 20, 48, 10),
    "gold200":     ("柯达 Gold 200",     24, 28, 40, 12),
    "pro400h":     ("富士 Pro 400H",     22, 26, 42, 10),
    "xtra400":     ("富士 Xtra 400",     30, 32, 38, 12),
    "vision3500t": ("柯达 Vision3 500T", 26, 30, 40, 14),
}


# ---------------------------------------------------------------- 颜色工具

def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    mx = rgb.max(-1); mn = rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-9
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    idx = nz & (mx == r); h[idx] = ((g - b)[idx] / d[idx]) % 6
    idx = nz & (mx == g); h[idx] = ((b - r)[idx] / d[idx]) + 2
    idx = nz & (mx == b); h[idx] = ((r - g)[idx] / d[idx]) + 4
    h = h * 60.0
    s = np.where(mx > 1e-9, d / np.maximum(mx, 1e-9), 0.0)
    return np.stack([h, s, mx], -1)


def hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h = (hsv[..., 0] % 360) / 60.0; s = hsv[..., 1]; v = hsv[..., 2]
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p = v * (1 - s); q = v * (1 - s * f); t = v * (1 - s * (1 - f))
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [v, q, p, p, t, v])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [t, v, v, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def apply(lut, pts: np.ndarray, pre_gain: float = PRE_GAIN) -> np.ndarray:
    """套 LUT（含曝光定位补偿，与 lr-filmsim / cube-to-hald 一致）"""
    x = np.clip(pts.reshape(1, -1, 3).astype(np.float32), 0, 1)
    if abs(pre_gain - 1.0) > 1e-6:
        x = core.linear_to_srgb(core.srgb_to_linear(x) * pre_gain).astype(np.float32)
    out = core._apply_3d(lut.astype(np.float32), x)
    return np.clip(out, 0, 1).reshape(-1, 3)


def monotonic(vals: list[float]) -> list[float]:
    out = [vals[0]]
    for v in vals[1:]:
        out.append(max(v, out[-1]))
    return out


# ---------------------------------------------------------------- 反解参数

def derive(lut, pre_gain: float) -> dict:
    # ① 三条通道曲线（中性灰轴）
    ins = np.linspace(0, 1, CURVE_POINTS)
    grays = np.repeat(ins[:, None], 3, axis=1)
    outs = apply(lut, grays, pre_gain)
    curves = {}
    ins255 = [round(float(i) * 255) for i in ins]
    # 复合曲线取三通道平均（中性响应）
    combo = monotonic([round(float(v) * 255) for v in outs.mean(axis=1)])
    curves[""] = list(zip(ins255, combo))
    for ci, tag in enumerate(("Red", "Green", "Blue")):
        vals = monotonic([round(float(v) * 255) for v in outs[:, ci]])
        curves[tag] = list(zip(ins255, vals))

    # ② 全局饱和度 / 鲜艳度
    rng = np.random.default_rng(7)
    hsv_s = np.stack([rng.uniform(0, 360, 200), rng.uniform(0.15, 1.0, 200),
                      rng.uniform(0.2, 0.9, 200)], -1)
    cin = hsv_to_rgb(hsv_s); cout = apply(lut, cin, pre_gain)
    hin = rgb_to_hsv(cin); hout = rgb_to_hsv(cout)
    m = hin[:, 1] > 0.12
    sat_delta = float(np.mean(hout[m, 1] / np.maximum(hin[m, 1], 1e-6)) - 1.0) * 100
    lows = hin[:, 1] < 0.35
    vib_delta = float(np.mean(hout[lows, 1] / np.maximum(hin[lows, 1], 1e-6)) - 1.0) * 100
    saturation = int(np.clip(round(sat_delta), -100, 100))
    vibrance = int(np.clip(round(vib_delta - sat_delta), -60, 60))

    # ③ 8 个色相带
    bands = {}
    for name, hue in BANDS:
        hs, ss, vs = [], [], []
        for sat in (0.45, 0.75):
            for val in (0.35, 0.55, 0.75):
                c = hsv_to_rgb(np.array([[hue, sat, val]]))
                o = apply(lut, c, pre_gain)
                hi = rgb_to_hsv(c)[0]; ho = rgb_to_hsv(o)[0]
                dh = ((ho[0] - hi[0] + 180) % 360) - 180
                hs.append(dh)
                ss.append((ho[1] / max(hi[1], 1e-6) - 1) * 100)
                vs.append((ho[2] - hi[2]) * 100)
        bands[name] = (
            int(np.clip(round(np.mean(hs) * 3.0), -100, 100)),   # LR 色相滑块 ≈ ±30° 满量程
            int(np.clip(round(np.mean(ss)), -100, 100)),
            int(np.clip(round(np.mean(vs)), -100, 100)),
        )

    # ④ 三段颜色分级（中性色的偏色）
    grading = {}
    for tag, lvl in (("Shadow", 0.20), ("Midtone", 0.5), ("Highlight", 0.80)):
        o = apply(lut, np.array([[lvl, lvl, lvl]]), pre_gain)[0]
        hsv = rgb_to_hsv(o[None])[0]
        sat = float(hsv[1]) * 100
        if sat * 1.2 < 3.0:
            grading[tag] = (0, 0)
        else:
            # 相对饱和度在暗部会被放大，这里限幅，避免预设一上去偏色过重
            grading[tag] = (int(round(float(hsv[0]) % 360)), int(np.clip(round(sat * 1.2), 3, 25)))

    return {"curves": curves, "saturation": saturation, "vibrance": vibrance,
            "bands": bands, "grading": grading}


# ---------------------------------------------------------------- XMP 生成

def xesc(v) -> str:
    """XML 文本节点转义：名字/分组里的 & < > 会直接生成非法 XMP。"""
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def xattr(v) -> str:
    """XML 属性值转义。"""
    return xesc(v).replace('"', "&quot;").replace("'", "&apos;")


def assert_parsable(path, what: str) -> None:
    """写盘后用标准解析器复读；生成非法 XMP 就直接失败，别交付出去。"""
    import xml.etree.ElementTree as ET
    try:
        ET.parse(str(path))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{what} 不是合法 XML：{path}\n  {type(exc).__name__}: {exc}") from exc


def xmp(name: str, group: str, d: dict, taste) -> str:
    _, grain_amt, grain_size, grain_freq, vignette = taste
    c = d["curves"]; b = d["bands"]; g = d["grading"]
    uid = uuid.uuid4().hex.upper()

    def curve(tag):
        pts = "\n".join(f"     <rdf:li>{int(i)}, {int(o)}</rdf:li>" for i, o in c[tag])
        elem = "ToneCurvePV2012" if tag == "" else f"ToneCurvePV2012{tag}"
        return (f"   <crs:{elem}>\n    <rdf:Seq>\n{pts}\n    </rdf:Seq>\n   </crs:{elem}>\n")

    def band_rows(key):
        return "".join(f'   crs:{key}{n}="{b[n][i]}"\n' for n in b for i in (0,)) \
            if False else "".join(f'   crs:{key}{n}="{b[n][i]}"\n' for n in b for i in (0,))

    lines = []
    for i, key in enumerate(("HueAdjustment", "SaturationAdjustment", "LuminanceAdjustment")):
        for n, _ in BANDS:
            lines.append(f'   crs:{key}{n}="{b[n][i]}"\n')

    body = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6-c140 79.160451, 2017/05/06-01:08:21">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Normal"
   crs:Cluster="{group}"
   crs:UUID="{xattr(uid)}"
   crs:SupportsAmount="False"
   crs:SupportsColor="True"
   crs:SupportsMonochrome="False"
   crs:SupportsHighDynamicRange="True"
   crs:SupportsNormalDynamicRange="True"
   crs:SupportsSceneReferred="True"
   crs:SupportsOutputReferred="True"
   crs:Version="15.0"
   crs:ProcessVersion="15.4"
   crs:HasSettings="True"
   crs:Amount="1.0"
   crs:AutoTone="False"
   crs:ToneCurveName2012="Custom"
   crs:Contrast2012="0"
   crs:Highlights2012="0"
   crs:Shadows2012="0"
   crs:Whites2012="0"
   crs:Blacks2012="0"
   crs:Clarity2012="0"
   crs:Texture="0"
   crs:Dehaze="0"
   crs:Saturation="{d['saturation']}"
   crs:Vibrance="{d['vibrance']}"
{''.join(lines)}   crs:ColorGradeBlending="50"
   crs:ColorGradeShadowHue="{g['Shadow'][0]}"
   crs:ColorGradeShadowSat="{g['Shadow'][1]}"
   crs:ColorGradeShadowLum="0"
   crs:ColorGradeMidtoneHue="{g['Midtone'][0]}"
   crs:ColorGradeMidtoneSat="{g['Midtone'][1]}"
   crs:ColorGradeMidtoneLum="0"
   crs:ColorGradeHighlightHue="{g['Highlight'][0]}"
   crs:ColorGradeHighlightSat="{g['Highlight'][1]}"
   crs:ColorGradeHighlightLum="0"
   crs:ColorGradeGlobalHue="0"
   crs:ColorGradeGlobalSat="0"
   crs:ColorGradeGlobalLum="0"
   crs:Sharpness="35"
   crs:SharpenRadius="+0.9"
   crs:SharpenDetail="20"
   crs:SharpenEdgeMasking="25"
   crs:LuminanceSmoothing="12"
   crs:ColorNoiseReduction="18"
   crs:GrainAmount="{grain_amt}"
   crs:GrainSize="{grain_size}"
   crs:GrainFrequency="{grain_freq}"
   crs:PostCropVignetteAmount="-{vignette}"
   crs:PostCropVignetteMidpoint="50"
   crs:PostCropVignetteFeather="60"
   crs:PostCropVignetteRoundness="0"
   crs:PostCropVignetteStyle="1"
   crs:PostCropVignetteHighlightContrast="0"
  >
{curve('')}{curve('Red')}{curve('Green')}{curve('Blue')}   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(name)}</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:ShortName>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(name)}</rdf:li>
    </rdf:Alt>
   </crs:ShortName>
   <crs:Group>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(group)}</rdf:li>
    </rdf:Alt>
   </crs:Group>
   <crs:Look
    crs:Name=""/>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=".cube → Lightroom XMP 预设（近似）")
    ap.add_argument("--dir", default=str(default_luts()))
    ap.add_argument("--out", default=str(ROOT / "lr-presets"))
    ap.add_argument("--group", default="胶片模拟")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--pre-gain", type=float, default=PRE_GAIN)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cubes = sorted(glob.glob(os.path.join(args.dir, "*.cube")))
    cubes = [c for c in cubes if not os.path.basename(c).startswith("identity")]
    if args.only:
        cubes = [c for c in cubes if any(k.lower() in os.path.basename(c).lower() for k in args.only)]
    if not cubes:
        print("没有可转换的 .cube")
        return 2

    print(f"{'胶片':22s} {'曲线(128→R/G/B)':>20s} {'饱和':>5s} {'鲜艳':>5s}  分级(阴影/中间/高光)")
    print("-" * 96)
    made = 0
    for c in cubes:
        stem = os.path.splitext(os.path.basename(c))[0]
        if stem not in TASTE:
            print(f"{stem:22s} 跳过（TASTE 表里没有，避免瞎猜颗粒/暗角）")
            continue
        lut, _ = core.load_lut(c)
        d = derive(lut, args.pre_gain)
        name, *_ = TASTE[stem]
        path = out_dir / f"{name}.xmp"
        path.write_text(xmp(name, args.group, d, TASTE[stem]), encoding="utf-8")
        assert_parsable(path, "近似预设")
        made += 1
        mid = [o for i, o in d["curves"][""] if i >= 128][:1]
        rgbs = []
        for tag in ("Red", "Green", "Blue"):
            rgbs.append([o for i, o in d["curves"][tag] if i >= 128][0])
        g = d["grading"]
        print(f"{name:22s} {str(rgbs):>20s} {d['saturation']:5d} {d['vibrance']:5d}  "
              f"{g['Shadow'][0]}°/{g['Shadow'][1]}  {g['Midtone'][0]}°/{g['Midtone'][1]}  "
              f"{g['Highlight'][0]}°/{g['Highlight'][1]}")

    print(f"\n生成 {made} 个 XMP → {out_dir}")
    if not made:
        print("\n✗ 没有生成任何文件——跳过 ≠ 成功。检查文件名是否在 TASTE 表里、或 --only 是否写错。",
              file=sys.stderr)
        return 1
    print("装进 Lightroom：")
    print(f"  mkdir -p ~/Library/Application\\ Support/Adobe/Lightroom/Develop\\ Presets/{args.group}")
    print(f"  cp {out_dir}/*.xmp ~/Library/Application\\ Support/Adobe/Lightroom/Develop\\ Presets/{args.group}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
