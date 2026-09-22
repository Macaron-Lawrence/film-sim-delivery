#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lut-to-ccprofile.py —— 把 .cube 胶片 LUT 打成 Adobe「创意配置文件」（Creative Profile）XMP。

这是 Fujifilm 那套 "dat + xml" 方案的同款机制（已从他们的文件里逆出格式并验证）：

  * 基础配置文件  .dcp  →  ~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/
                        （"Adobe Standard Linear"，按机型；Fujifilm 包里已经有 1464 个）
  * 创意配置文件  .xmp  →  ~/Library/Application Support/Adobe/CameraRaw/Settings/
                        内含 crs:RGBTable，即 base85+zlib 编码的 3D LUT（16bit 样本、delta 编码）
  * wrapper 预设  .xmp  →  同一目录，用 crs:Look 引用上面的 UUID，一键切换
  * .dat                →  Adobe 自动生成的配置文件索引缓存，不用管

对比 Lightroom「预设」只能近似（曲线+HSL），这条路径把 LUT **原样编码进 RGBTable**，
不做降级为曲线的近似。（不声称百分比：仓库没有可复现的保真度评分方法。）

二进制格式（逆出来的，与小节对应的解码器互相验证过）：
  u32 type=1, u32 version=1, u32 dims=3, u32 divisions
  samples[divisions^3][3] u16（LE），顺序 r 外层→g→b 内层；
     存的是「相对中性斜坡的增量」：stored = (actual - nop[idx]) & 0xFFFF
     nop[i] = (i*0xFFFF + divisions//2) // (divisions-1)
  u32 primaries, u32 gamma, u32 gamut, f64 min_amount, f64 max_amount[, u32 flags]
  再前面套：u32 未压缩长度 + zlib 流 → base85（Adobe 自定义字母表，小端 5 字符→4 字节）

用法：
  python3 scripts/lut-to-ccprofile.py                     # 全部胶片，默认线性基底
  python3 scripts/lut-to-ccprofile.py --space both        # 线性/显示两种都生成
  python3 scripts/lut-to-ccprofile.py --only portra400 --divisions 32
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
import sys
import hashlib
import struct
import uuid
import zlib
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

# Fujifilm 那套用的基础配置文件（用户机器上已装 1464 个 .dcp）
BASE_PROFILE = "Adobe Standard Linear"
BASE_DIGEST = "C580F12EA4FA42D05F7C67C881AF1401"
TITLE = {"linear": "线性基底", "display": "显示域"}

NAMES = {
    "portra400": "柯达 Portra 400", "portra160": "柯达 Portra 160", "portra800": "柯达 Portra 800",
    "ektar100": "柯达 Ektar 100", "gold200": "柯达 Gold 200",
    "pro400h": "富士 Pro 400H", "xtra400": "富士 Xtra 400", "vision3500t": "柯达 Vision3 500T",
    # —— spectral_film_lut 补的卷（见 tools/bake-spectral-luts.py）——
    "velvia50": "富士 Velvia 50（正片）",
    "ektachrome100d": "柯达 Ektachrome 100D（正片）",
    "provia100f": "富士 Provia 100F（正片）",
    "kodachrome64": "柯达 Kodachrome 64（正片）",
    "ektachrome100": "柯达 Ektachrome 100D（正片）",
    "aerochrome": "柯达 Aerochrome III（红外伪彩）",
    "instax": "富士 Instax",
    "fp100c": "富士 FP-100C",
    "trix400": "柯达 Tri-X 400（黑白）",
    "doublex5222": "柯达 Double-X 5222（黑白）",
    "trix_polymax": "柯达 Tri-X 400 × Polymax",
    "vision3_250d_2383": "柯达 Vision3 250D × 2383",
    "vision3_500t_2383": "柯达 Vision3 500T × 2383",
    "vision3_250d_2393": "柯达 Vision3 250D × 2393",
    "technicolor_v": "Technicolor V（5247）",
    "ektar100_sp": "柯达 Ektar 100（SFL）",
    "portra400_sp": "柯达 Portra 400（SFL）",
    "aerocolor": "柯达 Aerocolor IV",
    "agfa_vista100": "爱克发 Vista 100",
    "doublex5222_dev9": "柯达 Double-X 5222（Dev 9）",
    "ektar100_sfl": "柯达 Ektar 100（SFL）",
    "eterna_3513di": "富士 Eterna 500 × 3513DI",
    "eterna_vivid_3513": "富士 Eterna 500 Vivid × 3513DI",
    "gold200_sfl": "柯达 Gold 200（SFL）",
    "natura1600": "富士 Natura 1600",
    "portra400_fuji": "柯达 Portra 400 × Fuji CA",
    "portra400_sfl": "柯达 Portra 400（SFL）",
    "superia_reala": "富士 Superia Reala",
    "trix400_dev7": "柯达 Tri-X 400（Dev 7）",
    "vericolor_iii": "柯达 Vericolor III",
    "vision3_50d_2383": "柯达 Vision3 50D × 2383",
    # —— RawTherapee HaldCLUT 经典集（CC BY-SA 4.0）——
    "rt_ektar100": "柯达 Ektar 100（RT）",
    "rt_portra160": "柯达 Portra 160（RT）",
    "rt_portra400": "柯达 Portra 400（RT）",
    "rt_portra400vc": "柯达 Portra 400 VC（RT）",
    "rt_portra800": "柯达 Portra 800（RT）",
    "rt_kodachrome64": "柯达 Kodachrome 64（RT）",
    "rt_kodachrome25": "柯达 Kodachrome 25（RT）",
    "rt_ektachrome100vs": "柯达 Ektachrome 100 VS（RT）",
    "rt_elitechrome200": "柯达 Elite Chrome 200（RT）",
    "rt_eliteextracolor100": "柯达 Elite ExtraColor 100（RT）",
    "rt_velvia50": "富士 Velvia 50（RT）",
    "rt_provia100f": "富士 Provia 100F（RT）",
    "rt_astia100f": "富士 Astia 100F（RT）",
    "rt_fuji160c": "富士 160C（RT）",
    "rt_fuji400h": "富士 400H（RT）",
    "rt_fuji800z": "富士 800Z（RT）",
    "rt_superia_reala": "富士 Superia Reala（RT）",
    "rt_superia400": "富士 Superia 400（RT）",
    "rt_sensia100": "富士 Sensia 100（RT）",
    "rt_fp100c": "富士 FP-100C（RT）",
    "rt_agfa_vista200": "爱克发 Vista 200（RT）",
    "rt_agfa_ultra100": "爱克发 Ultra Color 100（RT）",
    "rt_agfa_precisa100": "爱克发 Precisa 100（RT）",
    "rt_polaroid690": "宝丽来 690（RT）",
    "rt_trix400": "柯达 Tri-X 400（RT）",
    "rt_tmax100": "柯达 T-Max 100（RT）",
    "rt_tmax400": "柯达 T-Max 400（RT）",
    "rt_tmax3200": "柯达 T-Max 3200（RT）",
    "rt_hie_infra": "柯达 HIE 红外（RT）",
    "rt_bw400cn": "柯达 BW 400 CN（RT）",
    "rt_hp5": "依尔福 HP5（RT）",
    "rt_delta100": "依尔福 Delta 100（RT）",
    "rt_delta3200": "依尔福 Delta 3200（RT）",
    "rt_fp4": "依尔福 FP4 Plus 125（RT）",
    "rt_panf50": "依尔福 Pan F Plus 50（RT）",
    "rt_xp2": "依尔福 XP2（RT）",
    "rt_acros100": "富士 Acros 100（RT）",
    "rt_neopan1600": "富士 Neopan 1600（RT）",
    "rt_apx100": "爱克发 APX 100（RT）",
    "rt_apx25": "爱克发 APX 25（RT）",
    "rt_rollei_ortho25": "禄来 Ortho 25（RT）",
    "rt_rollei_retro80s": "禄来 Retro 80s（RT）",
    "rt_rollei_ir400": "禄来 IR 400（RT）",
}

# ---------------------------------------------------------------- base85（Adobe 字母表）

_DIGIT_CHARS = ("0123456789" "abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                ".-:+ =^!/*?`'|()[]{}@%$#".replace(" ", ""))
assert len(_DIGIT_CHARS) == 85, len(_DIGIT_CHARS)


def b85_encode(data: bytes) -> str:
    out = []
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        pad = 4 - len(chunk)
        value = int.from_bytes(chunk + b"\x00" * pad, "little")
        chars = []
        for _ in range(5):
            chars.append(_DIGIT_CHARS[value % 85])
            value //= 85
        out.append("".join(chars[: 5 - pad + (1 if pad else 0)] if pad else chars))
    return "".join(out)


def b85_decode(text: str) -> bytes:
    idx = {c: i for i, c in enumerate(_DIGIT_CHARS)}
    out = bytearray(); phase = 0; value = 0
    for ch in text:
        if ch not in idx:
            continue
        d = idx[ch]; phase += 1
        value += d * (85 ** (phase - 1))
        if phase == 5:
            out += struct.pack("<I", value & 0xFFFFFFFF); phase = 0; value = 0
    if phase > 1:
        out += struct.pack("<I", value & 0xFFFFFFFF)[: phase - 1]
    return bytes(out)


# ---------------------------------------------------------------- 表格编解码

def nop_ramp(div: int) -> np.ndarray:
    i = np.arange(div, dtype=np.int64)
    return (i * 0xFFFF + (div >> 1)) // (div - 1)


# 表格元数据（primaries, gamma, gamut, min_amount, max_amount）
#   Fujifilm 那套（线性基底）：(3, 1, 0, 1.0, 1.0)
#   Adobe 自家创意配置文件（普通基底）：(1, 3, 0, 0.0, 1.0)
# 实测：这两种组合不能混用——用错会让 LR 按错误的空间解释表格，画面发灰。
META = {"linear": (3, 1, 0, 1.0, 1.0), "display": (1, 3, 0, 0.0, 1.0)}
BASE = {"linear": "Adobe Standard Linear", "display": "Adobe Standard"}


def encode_table(colors: np.ndarray, div: int, meta=(1, 3, 0, 0.0, 1.0)) -> bytes:
    """colors: (div,div,div,3) in 0..1 → Adobe RGBTable 二进制块"""
    assert colors.shape == (div, div, div, 3), colors.shape
    actual = np.rint(np.clip(colors, 0, 1) * 65535).astype(np.int64)
    ramp = nop_ramp(div)
    r = ramp[:, None, None]
    g = ramp[None, :, None]
    b = ramp[None, None, :]
    stored = np.stack([(actual[..., 0] - r) & 0xFFFF,
                       (actual[..., 1] - g) & 0xFFFF,
                       (actual[..., 2] - b) & 0xFFFF], axis=-1).astype("<u2")
    blob = struct.pack("<IIII", 1, 1, 3, div) + stored.tobytes()
    blob += struct.pack("<IIIdd", *meta)
    return struct.pack("<I", len(blob)) + zlib.compress(blob, 9)


def table_id(table_blob: bytes) -> str:
    """crs:RGBTable 的 ID 约定：解压后表内容的 MD5（大写十六进制）。
    实测 Fujifilm 与 Adobe 自带文件都满足这一约定。"""
    raw = table_blob[4:]
    data = zlib.decompress(raw)
    return hashlib.md5(data).hexdigest().upper()


def decode_table(text: str) -> tuple[np.ndarray, int]:
    """反向解析（用于自检）：→ (colors, div)"""
    data = zlib.decompress(b85_decode(text)[4:])
    t, v, dims, div = struct.unpack_from("<IIII", data, 0)
    assert (t, v, dims) == (1, 1, 3), (t, v, dims)
    n = div ** 3
    arr = np.frombuffer(data, dtype="<u2", count=n * 3, offset=16).reshape(n, 3).astype(np.int64)
    ramp = nop_ramp(div)
    ri, gi, bi = [a.ravel() for a in np.meshgrid(np.arange(div), np.arange(div), np.arange(div),
                                                 indexing="ij")]
    restore = np.stack([ramp[ri], ramp[gi], ramp[bi]], 1)
    return (((arr + restore) & 0xFFFF).astype(np.float64) / 65535.0).reshape(div, div, div, 3), div


# ---------------------------------------------------------------- 采样 LUT

def build_table(cube: Path, div: int, space: str, pre_gain: float,
                protect: float = 0.0, strength: float = 1.0) -> np.ndarray:
    lut, _ = core.load_lut(str(cube))
    axis = np.linspace(0, 1, div, dtype=np.float32)
    ri, gi, bi = np.meshgrid(axis, axis, axis, indexing="ij")
    pts = np.stack([ri, gi, bi], -1).reshape(1, -1, 3)

    if space == "linear":
        # 表格吃线性数据：先编码成显示域喂给 LUT，输出再解回线性
        enc = core.linear_to_srgb(pts).astype(np.float32)
    else:
        enc = pts.astype(np.float32)

    comp = core.linear_to_srgb(core.srgb_to_linear(enc) * pre_gain).astype(np.float32)
    out = np.clip(core._apply_3d(lut.astype(np.float32), comp), 0, 1).reshape(div, div, div, 3)

    if space == "linear":
        out = core.srgb_to_linear(out.astype(np.float32)).astype(np.float32)

    if protect > 0.0:
        # 护高光：以输入亮度为权，把高光平滑混回原始值
        #   L ≤ protect            → 完全用 LUT（保留胶片影调/色彩）
        #   L 从 protect 到 1.0    → smoothstep 过渡回原始
        #   L = 1.0                → 输出 = 输入（纯白仍是纯白，不再被肩部压到 0.82）
        base = pts.reshape(div, div, div, 3)
        lum = (0.2126 * base[..., 0] + 0.7152 * base[..., 1] + 0.0722 * base[..., 2])
        t = np.clip((lum - protect) / max(1e-6, 1.0 - protect), 0.0, 1.0)
        w = 1.0 - (t * t * (3.0 - 2.0 * t))
        out = out * w[..., None] + base * (1.0 - w[..., None])

    if strength < 1.0:
        # 强度烘焙：out_s = s·out + (1-s)·输入恒等
        # 与 lr-filmsim.py --strength 同一套语义（都是跟**输入**线性混合），
        # 区别只是这里把结果固定进表里。s=1 时完全不变（默认）。
        base_all = pts.reshape(div, div, div, 3)
        out = out * float(strength) + base_all * (1.0 - float(strength))
    return out.astype(np.float32)


# ---------------------------------------------------------------- XMP 模板

def xesc(v) -> str:
    """XML 文本节点转义。文件名/分组名里的 & < > 会直接破坏 XMP——
    实测 `Warm & Soft.cube` 与 `Client <Final>.cube` 生成的 4 个 XMP 全部无法被标准解析器读取。"""
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def xattr(v) -> str:
    """XML 属性值转义。

    只转义在**双引号属性**里真正会破坏解析的三个字符：`&` `<` `"`。
    **不能**转义单引号：Adobe 的 base85 字母表里就含 `'`，把表数据里的 `'` 换成
    `&apos;` 会直接毁掉 RGBTable（实测解码报 zlib error: invalid code）。
    同理不能把 `>` 之外的东西再包一层。
    """
    return xesc(v).replace(">", "&gt;").replace('"', "&quot;")


def assert_parsable(path, what: str) -> None:
    """写盘后用标准 XML 解析器复读。宁可在这里失败，也不要交付一个 LR 读不进去的文件。"""
    import xml.etree.ElementTree as ET
    try:
        ET.parse(str(path))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{what} 不是合法 XML：{path}\n  {type(exc).__name__}: {exc}") from exc


def look_xmp(name: str, table_id: str, payload: str, base_profile: str, digest: str,
             look_uuid: str, description: str, group: str = "胶片模拟 (光谱 LUT)") -> str:
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Look"
   crs:Cluster=""
   crs:UUID="{xattr(look_uuid)}"
   crs:SupportsAmount="False"
   crs:SupportsColor="True"
   crs:SupportsMonochrome="False"
   crs:SupportsHighDynamicRange="True"
   crs:SupportsNormalDynamicRange="True"
   crs:SupportsSceneReferred="True"
   crs:SupportsOutputReferred="False"
   crs:RequiresRGBTables="False"
   crs:ShowInPresets="True"
   crs:ShowInQuickActions="False"
   crs:CameraModelRestriction=""
   crs:Copyright=""
   crs:ContactInfo=""
   crs:Version="18.1.1"
   crs:ProcessVersion="15.4"
   crs:ConvertToGrayscale="False"
   crs:CameraProfile="{xattr(base_profile)}"
   crs:CameraProfileDigest="{xattr(digest)}"
   crs:RGBTable="{xattr(table_id)}"
   crs:Table_{xattr(table_id)}="{xattr(payload)}"
   crs:HasSettings="True">
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(name)}</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:ShortName>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:ShortName>
   <crs:SortName>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:SortName>
   <crs:Group>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(group)}</rdf:li>
    </rdf:Alt>
   </crs:Group>
   <crs:Description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(description)}</rdf:li>
    </rdf:Alt>
   </crs:Description>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def wrapper_xmp(name: str, look_uuid: str, group: str, amount: float = 1.0,
                supports_amount: bool = False) -> str:
    # Amount 是这个 Look 被施加时的强度（0–1），Adobe/Fujifilm 官方预设就是用它。
    # SupportsAmount/SupportsAmount2 决定 Lightroom 是否给出可拖的"Amount"滑块：
    #   · 官方（Fujifilm 整套）写的是 False —— 强度被固定成预设里的 Amount；
    #   · 写 True 是否真能让滑块出现，需要在真实 Lightroom 里验证，CI 测不到，
    #     所以默认保持 False（与官方一致），要试就加 --supports-amount。
    AMT_TRUE, AMT_FALSE = "True", "False"
    wuid = uuid.uuid4().hex.upper()
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Normal"
   crs:Cluster=""
   crs:UUID="{xattr(wuid)}"
   crs:SupportsAmount2="{AMT_TRUE if supports_amount else AMT_FALSE}"
   crs:SupportsAmount="{AMT_TRUE if supports_amount else AMT_FALSE}"
   crs:SupportsColor="True"
   crs:SupportsMonochrome="True"
   crs:SupportsHighDynamicRange="True"
   crs:SupportsNormalDynamicRange="True"
   crs:SupportsSceneReferred="True"
   crs:SupportsOutputReferred="True"
   crs:RequiresRGBTables="False"
   crs:ShowInPresets="True"
   crs:ShowInQuickActions="False"
   crs:CameraModelRestriction=""
   crs:Copyright=""
   crs:ContactInfo=""
   crs:Version="18.1.1"
   crs:ProcessVersion="15.4"
   crs:HasSettings="True">
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(name)}</rdf:li>
    </rdf:Alt>
   </crs:Name>
   <crs:ShortName>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:ShortName>
   <crs:SortName>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:SortName>
   <crs:Group>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xesc(group)}</rdf:li>
    </rdf:Alt>
   </crs:Group>
   <crs:Description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:Description>
   <crs:Look
    crs:Name="{xattr(name)}"
    crs:Amount="{amount:g}"
    crs:UUID="{xattr(look_uuid)}"
    crs:SupportsAmount="false"
    crs:SupportsMonochrome="false"
    crs:SupportsOutputReferred="false"
    crs:Stubbed="true"/>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=".cube → Adobe 创意配置文件 XMP（真 3D LUT）")
    ap.add_argument("--dir", default=str(default_luts()))
    ap.add_argument("--out", default=str(ROOT / "lr-ccprofiles"))
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--divisions", type=int, default=32, help="每个轴的采样数（Adobe 用 16/32）")
    ap.add_argument("--space", choices=["linear", "display", "both"], default="linear",
                    help="表格接收的数据空间：线性基底用 linear；若在 LR 里明显不对就试 display")
    ap.add_argument("--base-profile", default=None,
                    help="默认按空间自动选：linear→Adobe Standard Linear，display→Adobe Standard")
    ap.add_argument("--base-digest", default=None)
    ap.add_argument("--pre-gain", type=float, default=0.3472,
                    help="曝光定位补偿：0.3472=中灰严格归位(默认)；0.45=平均亮度匹配")
    ap.add_argument("--label", default="", help="追加到名字里的标签，例如 亮度匹配")
    ap.add_argument("--calibration", default=None,
                    help="calibrate-luts.py 产出的 JSON；按 LUT 名取各自的 pre-gain")
    ap.add_argument("--mode", choices=["midgray", "brightness"], default=None,
                    help="声明这份标定是用哪个模式算的；与 --calibration 一起用时必须给，"
                         "脚本会核对，不一致直接拒绝（标定契约的另一半）")
    ap.add_argument("--only-known", action="store_true",
                    help="只处理内置 NAMES 表里的胶片名；默认处理**任意文件名**")
    ap.add_argument("--allow-unknown", action="store_true",
                    help="（已过时，默认即此行为；保留仅为兼容旧命令行）")
    ap.add_argument("--group", default="胶片模拟 (光谱 LUT)",
                    help="在 LR 配置文件浏览器里显示的分组名")
    ap.add_argument("--protect", type=float, default=0.0,
                    help="护高光阈值 0~1（如 0.62=亮度超过 158/255 的部分平滑混回原样，"
                         "L=1.0 时输出=输入，纯白保持 255，不再受胶片肩部压制）")
    ap.add_argument("--bake-strength", type=float, default=1.0,
                    help="把强度**烘焙进表里**：out = s·LUT + (1-s)·输入（默认 1=不降级）。"
                         "产出的配置文件本身就是'50%% 强度'，不依赖宿主的 Amount 滑块")
    ap.add_argument("--amounts", default="",
                    help="额外生成几个不同强度的 wrapper 预设（逗号分隔，如 1,0.75,0.5,0.25）。"
                         "它们共用同一张表、同一个 Look UUID，只是 crs:Amount 不同——"
                         "文件只有 1KB 级，不重复表数据")
    ap.add_argument("--supports-amount", action="store_true",
                    help="在预设上声明 SupportsAmount2/SupportsAmount=True，"
                         "尝试让 Lightroom 给出可拖的强度滑块。**该行为未在真实 LR 中验证**，"
                         "默认关闭（与 Adobe/Fujifilm 官方预设一致，官方写的是 False）")
    args = ap.parse_args()

    # 参数范围校验：宁可在这里拒绝，也不要产出一个看着正常、其实参数已经越界的交付
    bad = []
    if not (1 <= args.divisions <= 64):
        bad.append(f"--divisions {args.divisions}（要求 1–64）")
    if not (0.0 <= args.protect < 1.0):
        bad.append(f"--protect {args.protect}（要求 0 ≤ protect < 1）")
    if not (0.0 < args.bake_strength <= 1.0):
        bad.append(f"--bake-strength {args.bake_strength}（要求 0 < s ≤ 1；0 等于不用这张 LUT）")
    if not (0.01 <= args.pre_gain <= 8.0):
        bad.append(f"--pre-gain {args.pre_gain}（要求 0.01–8.0）")
    if args.space not in ("display", "linear", "both"):
        bad.append(f"--space {args.space}（要求 display / linear / both）")
    if bad:
        print("✗ 参数越界，已中止：", file=sys.stderr)
        for b in bad:
            print(f"    {b}", file=sys.stderr)
        return 2

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    cubes = sorted(glob.glob(os.path.join(args.dir, "*.cube"))
                   + glob.glob(os.path.join(args.dir, "*.png"))
                   + glob.glob(os.path.join(args.dir, "*.tif")))
    cubes = [c for c in cubes if not os.path.basename(c).startswith("identity")]
    if args.only:
        cubes = [c for c in cubes if any(k.lower() in os.path.basename(c).lower() for k in args.only)]
    if not cubes:
        print(f"[lut-to-ccprofile] {args.dir} 下没有 .cube / .png / .tif", file=sys.stderr)
        return 1

    calib = {}
    if args.calibration:
        import json as _json
        if not os.path.exists(args.calibration):
            print(f"[lut-to-ccprofile] 标定文件不存在：{args.calibration}", file=sys.stderr)
            return 2
        calib = _json.loads(open(args.calibration, encoding="utf-8").read())
        print(f"读入标定 {len(calib)} 条：{args.calibration}")

        # 标定与生成必须同口径，否则交付的影调不是标定时承诺的那个。
        # 过去这里只读 pre_gain，protect 不一致也照样生成——由脚本拒绝，而不是靠文档提醒。
        modes = {str(v.get("mode")) for v in calib.values() if isinstance(v, dict) and v.get("mode")}
        if not args.mode:
            print("\n✗ 用了 --calibration 就必须同时声明 --mode（midgray 或 brightness）。\n"
                  "  标定与生成必须同口径，而「生成时用的是哪个模式」只有调用方知道；"
                  "不声明就无法核对，等于把契约交给运气。", file=sys.stderr)
            return 2
        if modes and args.mode not in modes:
            print(f"\n✗ --mode {args.mode} 与标定文件里记录的模式 {sorted(modes)} 不一致，已中止。",
                  file=sys.stderr)
            return 1
        bad = []
        for stem, v in sorted(calib.items()):
            if not isinstance(v, dict):
                continue
            if "protect" not in v or "pre_gain" not in v:
                bad.append((stem, "标定条目缺 protect/pre_gain 字段（旧的标定文件请重跑 calibrate-luts.py）"))
            elif abs(float(v["protect"]) - args.protect) > 1e-9:
                bad.append((stem, f"标定时 protect={v['protect']}，本次 --protect {args.protect}"))
        if modes and len(modes) > 1:
            bad.append(("(整份标定)", f"标定文件里混用了多种 mode：{sorted(modes)}"))
        if bad:
            print(f"\n✗ 标定参数与本次生成不一致，已中止，未生成任何文件：", file=sys.stderr)
            for stem, why in bad[:10]:
                print(f"    {stem}: {why}", file=sys.stderr)
            if len(bad) > 10:
                print(f"    …以及另外 {len(bad)-10} 条", file=sys.stderr)
            print(f"  标定与生成必须用同一个 --mode/--protect。"
                  f"请按本次的 --protect {args.protect} 重跑标定，或把生成命令改成标定时用的值。",
                  file=sys.stderr)
            return 1
        if modes:
            print(f"  标定口径核对通过：mode={sorted(modes)[0]}，protect={args.protect}")

    try:
        amounts = [float(x) for x in args.amounts.split(",") if x.strip()] or [1.0]
    except ValueError:
        print(f"✗ --amounts 解析失败：{args.amounts!r}（应形如 1,0.75,0.5）", file=sys.stderr)
        return 2
    for a in amounts:
        if not (0.0 < a <= 1.0):
            print(f"✗ --amounts 里有越界值 {a}（要求 0 < a ≤ 1）", file=sys.stderr)
            return 2
    amounts = sorted(set(amounts), reverse=True)

    spaces = ["linear", "display"] if args.space == "both" else [args.space]
    made, skipped_known, failed = [], [], []
    for c in cubes:
        stem = os.path.splitext(os.path.basename(c))[0]
        if stem not in NAMES and args.only_known:
            skipped_known.append(stem)
            continue
        for sp in spaces:
          try:
            gain = float(calib.get(stem, {}).get("pre_gain", args.pre_gain))
            colors = build_table(Path(c), args.divisions, sp, gain, args.protect,
                                 args.bake_strength)
            blob = encode_table(colors, args.divisions, META[sp])
            # 自检：解回来必须与写入一致
            back, div2 = decode_table(b85_encode(blob))
            err = float(np.abs(back - colors).max()) * 65535
            assert div2 == args.divisions and err < 1.0, f"自检失败 err={err}"

            name = f"{NAMES.get(stem, stem)}（{TITLE[sp]}{args.label}）"
            look_uuid = uuid.uuid4().hex.upper()
            tid = table_id(blob)
            payload = b85_encode(blob)
            assert not any(ch in payload for ch in '&<>"'), \
                "base85 表数据里出现了 XML 特殊字符——转义会毁掉表，编码器需先修正"
            desc = (f"spektrafilm 光谱胶片 LUT → Adobe 创意配置文件；"
                    f"{args.divisions}^3 网格，输入空间={'线性' if sp=='linear' else '显示域'}，"
                    f"已做曝光定位补偿")
            base = args.base_profile if args.base_profile else BASE[sp]
            digest = args.base_digest if args.base_profile else (BASE_DIGEST if sp == "linear" else "")
            prof_path = out_dir / f"{name}.xmp"
            prof_path.write_text(look_xmp(name, tid, payload, base, digest, look_uuid,
                                          desc, args.group), encoding="utf-8")
            # 生成即验证：写出的文件必须能被标准 XML 解析器读回
            assert_parsable(prof_path, "创意配置文件")

            # wrapper 预设：--amounts 会生成多个强度，共用同一个 Look UUID 与同一张表，
            # 只是 crs:Amount 不同（Adobe/Fujifilm 官方就是这个结构）
            for amt in amounts:
                suffix = "" if amt >= 1.0 else f"（{amt * 100:g}%）"
                wrap_path = out_dir / f"{name}{suffix} wrapper.xmp"
                wrap_path.write_text(
                    wrapper_xmp(name + suffix, look_uuid, args.group, amt,
                                args.supports_amount), encoding="utf-8")
                assert_parsable(wrap_path, "wrapper 预设")
            made.append((name, len(payload), err))
            extra = "" if amounts == [1.0] else f"  预设强度={'/'.join(f'{a*100:g}%' for a in amounts)}"
            baked = "" if args.bake_strength >= 1.0 else f"  [烘焙强度 {args.bake_strength*100:g}%]"
            print(f"✓ {name[:26]:26s} pre-gain={gain:.3f}  {len(payload)/1024:5.0f}KB  基底={base}"
                  f"{extra}{baked}"[:118])
          except Exception as exc:  # noqa: BLE001
            failed.append((stem, f"{type(exc).__name__}: {exc}"))
            print(f"✗ {stem}: {exc}", file=sys.stderr)
            # 不留半成品：只删本次刚写出的那两个**确定的**路径。
            # 注意不能用 glob(f"*{stem}*.xmp")：stem 里若含 * ? [ ] 会被当通配符，
            # 实测 stem="*" 时该模式会命中并删除输出目录里其他交付文件。
            name_try = f"{NAMES.get(stem, stem)}（{TITLE[sp]}{args.label}）"
            for bad in (out_dir / f"{name_try}.xmp", out_dir / f"{name_try} wrapper.xmp"):
                try:
                    if bad.is_file():
                        bad.unlink()
                except OSError:
                    pass
    print(f"\n生成 {len(made)} 个创意配置文件（含 wrapper 预设）→ {out_dir}")
    if failed:
        print(f"✗ {len(failed)} 个失败：", file=sys.stderr)
        for stem, why in failed[:5]:
            print(f"    {stem}: {why}", file=sys.stderr)
    if skipped_known:
        print(f"（--only-known：按内置 NAMES 表跳过了 {len(skipped_known)} 个："
              f"{skipped_known[:5]}…）")
    # 零产物必须是失败：退出码 0 + "生成 0 个" 会让 Agent 误报完成。
    if not made:
        print("\n✗ 没有生成任何配置文件——这不算成功，请检查输入目录与参数。", file=sys.stderr)
        return 1
    if failed:
        return 1
    print("安装： python3 scripts/install_ccprofiles.py list   # 先看清单，再 install")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
