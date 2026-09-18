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

对比 Lightroom「预设」只能近似（曲线+HSL），这条路径是**真 3D LUT**，保真度 100%。

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

import argparse
import glob
import importlib.util
import os
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
                protect: float = 0.0) -> np.ndarray:
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
    return out.astype(np.float32)


# ---------------------------------------------------------------- XMP 模板

def look_xmp(name: str, table_id: str, payload: str, base_profile: str, digest: str,
             look_uuid: str, description: str, group: str = "胶片模拟 (光谱 LUT)") -> str:
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Look"
   crs:Cluster=""
   crs:UUID="{look_uuid}"
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
   crs:CameraProfile="{base_profile}"
   crs:CameraProfileDigest="{digest}"
   crs:RGBTable="{table_id}"
   crs:Table_{table_id}="{payload}"
   crs:HasSettings="True">
   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{name}</rdf:li>
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
     <rdf:li xml:lang="x-default">{group}</rdf:li>
    </rdf:Alt>
   </crs:Group>
   <crs:Description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{description}</rdf:li>
    </rdf:Alt>
   </crs:Description>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def wrapper_xmp(name: str, look_uuid: str, group: str) -> str:
    wuid = uuid.uuid4().hex.upper()
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   crs:PresetType="Normal"
   crs:Cluster=""
   crs:UUID="{wuid}"
   crs:SupportsAmount2="False"
   crs:SupportsAmount="False"
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
     <rdf:li xml:lang="x-default">{name}</rdf:li>
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
     <rdf:li xml:lang="x-default">{group}</rdf:li>
    </rdf:Alt>
   </crs:Group>
   <crs:Description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default"/>
    </rdf:Alt>
   </crs:Description>
   <crs:Look
    crs:Name="{name}"
    crs:Amount="1"
    crs:UUID="{look_uuid}"
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
    ap.add_argument("--allow-unknown", action="store_true",
                    help="不在 NAMES 表里的 .cube 也用文件名当显示名")
    ap.add_argument("--group", default="胶片模拟 (光谱 LUT)",
                    help="在 LR 配置文件浏览器里显示的分组名")
    ap.add_argument("--protect", type=float, default=0.0,
                    help="护高光阈值 0~1（如 0.62=亮度超过 158/255 的部分平滑混回原样，"
                         "纯白保持 255，不再被胶片肩部压到 ~209）")
    args = ap.parse_args()

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    cubes = sorted(glob.glob(os.path.join(args.dir, "*.cube"))
                   + glob.glob(os.path.join(args.dir, "*.png"))
                   + glob.glob(os.path.join(args.dir, "*.tif")))
    cubes = [c for c in cubes if not os.path.basename(c).startswith("identity")]
    if args.only:
        cubes = [c for c in cubes if any(k.lower() in os.path.basename(c).lower() for k in args.only)]
    if not cubes:
        print("没有 .cube"); return 2

    calib = {}
    if args.calibration and os.path.exists(args.calibration):
        import json as _json
        calib = _json.loads(open(args.calibration, encoding="utf-8").read())
        print(f"读入标定 {len(calib)} 条：{args.calibration}")

    spaces = ["linear", "display"] if args.space == "both" else [args.space]
    made = []
    for c in cubes:
        stem = os.path.splitext(os.path.basename(c))[0]
        if stem not in NAMES and not args.allow_unknown:
            continue
        for sp in spaces:
            gain = float(calib.get(stem, {}).get("pre_gain", args.pre_gain))
            colors = build_table(Path(c), args.divisions, sp, gain, args.protect)
            blob = encode_table(colors, args.divisions, META[sp])
            # 自检：解回来必须与写入一致
            back, div2 = decode_table(b85_encode(blob))
            err = float(np.abs(back - colors).max()) * 65535
            assert div2 == args.divisions and err < 1.0, f"自检失败 err={err}"

            name = f"{NAMES.get(stem, stem)}（{TITLE[sp]}{args.label}）"
            look_uuid = uuid.uuid4().hex.upper()
            tid = table_id(blob)
            payload = b85_encode(blob)
            desc = (f"spektrafilm 光谱胶片 LUT → Adobe 创意配置文件；"
                    f"{args.divisions}^3 网格，输入空间={'线性' if sp=='linear' else '显示域'}，"
                    f"已做曝光定位补偿")
            base = args.base_profile if args.base_profile else BASE[sp]
            digest = args.base_digest if args.base_profile else (BASE_DIGEST if sp == "linear" else "")
            (out_dir / f"{name}.xmp").write_text(
                look_xmp(name, tid, payload, base, digest, look_uuid, desc,
                         args.group), encoding="utf-8")
            (out_dir / f"{name} wrapper.xmp").write_text(
                wrapper_xmp(name, look_uuid, "胶片模拟 (光谱 LUT)"), encoding="utf-8")
            made.append((name, len(payload), err))
            print(f"✓ {name:30s} pre-gain={gain:.3f}  {len(payload)/1024:5.0f}KB  基底={base}"[:112])
    print(f"\n生成 {len(made)} 个创意配置文件（含 wrapper 预设）→ {out_dir}")
    print("安装： scripts/install-lr-ccprofiles.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
