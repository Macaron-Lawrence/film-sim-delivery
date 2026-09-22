#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lr-filmsim.py — 给 Lightroom 工作流用的胶片模拟 LUT 施加器

支持：
  * 3D LUT：.cube（LUT_3D_SIZE，可含 LUT_1D_SIZE shaper）
  * HaldCLUT：PNG（level 自动识别）
  * 图像：TIFF 8/16/32bit（走 tifffile）、PNG/JPEG 等（走 Pillow）
  * 原地改写（External Editor 用）或 --out DIR 另存（导出/监听流水线用）

用法：
  lr-filmsim.py --lut kodak_portra_400.cube photo.tif            # 原地改写
  lr-filmsim.py --lut p400.cube --out ./out a.jpg b.tif          # 另存到 out/
  lr-filmsim.py --lut p400.cube --strength 0.6 photo.tif         # 混合 60%
  lr-filmsim.py --lut p400.cube --linear-pipeline photo.tif      # LUT 为 linear→linear 时用
  lr-filmsim.py --lut p400.png --info                            # 只看 LUT 信息
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
import os
import json
import shutil
import sys
import time
import tempfile

import numpy as np

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import tifffile
except ImportError:  # pragma: no cover
    tifffile = None

TIFF_EXT = {".tif", ".tiff", ".btf", ".dng"}
CHUNK_ROWS = 512  # 分块处理，控制内存峰值


# ---------------------------------------------------------------- LUT 读取

def _read_cube(path: str):
    lut1d = None
    size = None
    domain_min = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    domain_max = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    data1d: list[list[float]] = []
    data3d: list[list[float]] = []
    cur = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            head = line.split()[0].upper()
            if head == "TITLE":
                continue
            if head == "LUT_3D_SIZE":
                size = int(line.split()[1])
                cur = data3d
                continue
            if head == "LUT_1D_SIZE":
                lut1d_size = int(line.split()[1])
                lut1d = np.zeros((lut1d_size, 3), dtype=np.float64)
                # 1D 数据也逐行给，先标记
                cur = data1d
                data1d.clear()
                continue
            if head == "DOMAIN_MIN":
                domain_min = np.array([float(x) for x in line.split()[1:4]])
                continue
            if head == "DOMAIN_MAX":
                domain_max = np.array([float(x) for x in line.split()[1:4]])
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                vals = [float(parts[0]), float(parts[1]), float(parts[2])]
            except ValueError:
                continue
            if cur is not None:
                cur.append(vals)

    if lut1d is not None and data1d:
        arr1 = np.asarray(data1d, dtype=np.float64)
        if arr1.shape[0] >= lut1d.shape[0]:
            lut1d = arr1[: lut1d.shape[0]]
        else:
            lut1d = None  # 数据不足，忽略 shaper
    if size is None or not data3d:
        raise SystemExit(f"[lr-filmsim] 不是有效的 3D .cube：{path}")

    arr = np.asarray(data3d, dtype=np.float64)
    need = size ** 3
    if arr.shape[0] < need:
        raise SystemExit(f"[lr-filmsim] LUT 数据不足：需要 {need} 行，只有 {arr.shape[0]} 行")
    arr = arr[:need]
    # .cube：红变化最快 -> flat[i], i = r + g*N + b*N^2 -> reshape(N,N,N) 得到 [b][g][r]
    lut = arr.reshape(size, size, size, 3)
    span = np.where((domain_max - domain_min) == 0, 1.0, domain_max - domain_min)
    lut = (lut - domain_min) / span
    lut = np.clip(lut, 0.0, 1.0).astype(np.float32)
    return lut, lut1d


def _read_hald(path: str) -> np.ndarray:
    if Image is None:
        raise SystemExit("[lr-filmsim] HaldCLUT 需要 Pillow")
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w != h:
        raise SystemExit("[lr-filmsim] HaldCLUT 必须是正方形")
    total = w * h
    level = int(round(total ** (1.0 / 3.0)))
    if level ** 3 != total:
        for cand in range(2, 65):
            if cand ** 3 == total:
                level = cand
                break
        else:
            raise SystemExit(f"[lr-filmsim] 无法从尺寸 {w}x{h} 推断 HaldCLUT level")
    arr_in = np.asarray(img)
    maxv = 255.0 if arr_in.dtype == np.uint8 else 65535.0 if arr_in.dtype == np.uint16 else 1.0
    flat = arr_in.reshape(-1, 3)
    # 大网格（如 level 16 = 256³）先降采样，避免几百 MB 内存
    if level > 64:
        step = int(np.ceil(level / 48.0))
        keep = np.arange(0, level, step)
        grid = flat.reshape(level, level, level, 3)[np.ix_(keep, keep, keep)]
        lut = grid.astype(np.float32) / np.float32(maxv)
        return np.clip(lut, 0.0, 1.0).astype(np.float32)
    flat = flat.astype(np.float64) / maxv
    # flat[i], i = r + g*N + b*N^2  -> reshape(N,N,N) 得到 [b][g][r]
    lut = flat.reshape(level, level, level, 3)
    return np.clip(lut, 0.0, 1.0).astype(np.float32)


def load_lut(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cube":
        return _read_cube(path)
    if ext in (".png", ".tif", ".tiff"):
        return _read_hald(path), None
    raise SystemExit(f"[lr-filmsim] 不支持的 LUT 格式：{ext}（用 .cube 或 HaldCLUT PNG）")


# ---------------------------------------------------------------- 图像 IO

def read_image(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext in TIFF_EXT and tifffile is not None:
        arr = tifffile.imread(path)
        return arr, "tiff"
    if Image is None:
        raise SystemExit("[lr-filmsim] 读取该格式需要 Pillow")
    img = Image.open(path)
    icc = img.info.get("icc_profile")
    arr = np.asarray(img)
    return arr, ("pil", icc)


def write_image(path: str, arr: np.ndarray, kind, meta=None):
    ext = os.path.splitext(path)[1].lower()
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".lrfilmsim-", suffix=ext)
    os.close(fd)
    try:
        if kind == "tiff" and tifffile is not None:
            tifffile.imwrite(tmp, arr, photometric="rgb" if arr.ndim == 3 and arr.shape[2] == 3 else None)
        else:
            icc = meta if isinstance(meta, (bytes, bytearray)) else None
            img = Image.fromarray(arr)
            kw = {}
            if icc:
                kw["icc_profile"] = icc
            if ext in (".jpg", ".jpeg"):
                kw.update(quality=97, subsampling=0)
            img.save(tmp, **kw)
        os.replace(tmp, path)  # 原子替换，Lightroom 能感知到文件更新
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- 计算

def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _apply_3d(lut: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    n = lut.shape[0]
    flat = lut.reshape(-1, 3)
    c = np.clip(rgb, 0.0, 1.0) * (n - 1)
    i0 = np.floor(c).astype(np.int32)
    frac = (c - i0).astype(np.float32)
    i1 = np.minimum(i0 + 1, n - 1)
    i0 = i0.astype(np.int64)
    i1 = i1.astype(np.int64)

    out = np.zeros_like(rgb, dtype=np.float32)
    for db in (0, 1):
        wb = frac[..., 2] if db else (1.0 - frac[..., 2])
        zb = i1[..., 2] if db else i0[..., 2]
        for dg in (0, 1):
            wg = frac[..., 1] if dg else (1.0 - frac[..., 1])
            zg = i1[..., 1] if dg else i0[..., 1]
            for dr in (0, 1):
                wr = frac[..., 0] if dr else (1.0 - frac[..., 0])
                zr = i1[..., 0] if dr else i0[..., 0]
                # lut 内存布局是 [b][g][r]，C-order 展平后 index = r + g*n + b*n^2
                idx = (zb * n + zg) * n + zr
                wt = (wr * wg * wb).astype(np.float32)[..., None]
                gathered = flat[idx.reshape(-1)].reshape(rgb.shape).astype(np.float32, copy=False)
                out += wt * gathered
    return out


def apply_lut(rgb: np.ndarray, lut: np.ndarray, lut1d=None, strength: float = 1.0,
              linear_pipeline: bool = False, pre_gain: float = 1.0) -> np.ndarray:
    """pre_gain：套 LUT 之前施加的曝光位移（线性域乘系数后重新编码）。
    spektrafilm 的 bundle 默认把"源白点放在 +4 档"（内部线性增益 2.88），
    所以直接套会整体亮约 1.5 档；--pre-gain 0.35 可把中灰放回原位。"""
    h = rgb.shape[0]
    out = np.empty_like(rgb, dtype=np.float32)
    shift = abs(pre_gain - 1.0) > 1e-6
    for y in range(0, h, CHUNK_ROWS):
        blk = rgb[y:y + CHUNK_ROWS].astype(np.float32)
        src = blk
        if shift:  # 在线性域改变曝光，再编码回 sRGB（LUT 本身吃 sRGB 编码值）
            src = linear_to_srgb(srgb_to_linear(src) * pre_gain)
        if linear_pipeline:
            src = srgb_to_linear(src)
        if lut1d is not None:
            n1 = lut1d.shape[0]
            c = np.clip(src, 0.0, 1.0) * (n1 - 1)
            j0 = np.floor(c).astype(np.int64)
            f = (c - j0).astype(np.float32)
            j1 = np.minimum(j0 + 1, n1 - 1)
            l1 = lut1d.astype(np.float32)
            src = (1 - f) * l1[j0.reshape(-1)].reshape(src.shape) + f * l1[j1.reshape(-1)].reshape(src.shape)
        res = _apply_3d(lut, src)
        if linear_pipeline:
            res = linear_to_srgb(res)
        if strength < 1.0:
            res = blk * (1.0 - strength) + res * strength
        out[y:y + CHUNK_ROWS] = np.clip(res, 0.0, 1.0)
    return out


def to_float(arr: np.ndarray) -> tuple[np.ndarray, str]:
    if arr.dtype == np.uint8:
        return arr.astype(np.float32) / 255.0, "u8"
    if arr.dtype == np.uint16:
        return arr.astype(np.float32) / 65535.0, "u16"
    if arr.dtype == np.uint32:
        return arr.astype(np.float32) / 4294967295.0, "u32"
    a = arr.astype(np.float32)
    if a.size and float(np.nanmax(a)) > 1.5:          # 16bit 范围的 float
        return np.clip(a / 65535.0, 0, 1), "f32-16"
    return np.clip(a, 0, 1), "f32"


def from_float(f: np.ndarray, kind: str) -> np.ndarray:
    if kind == "u8":
        return np.rint(f * 255.0).astype(np.uint8)
    if kind == "u16":
        return np.rint(f * 65535.0).astype(np.uint16)
    if kind == "u32":
        return np.rint(f * 4294967295.0).astype(np.uint32)
    if kind == "f32-16":
        return (f * 65535.0).astype(np.float32)
    return f.astype(np.float32)


# ---------------------------------------------------------------- main

def protect_blend(out: np.ndarray, base: np.ndarray, protect: float) -> np.ndarray:
    """护高光：与 lut-to-ccprofile.py 的 build_table() 同一套公式。

    按**输入亮度**加权把高光平滑混回原始值：
        L ≤ protect          → 完全用 LUT
        protect < L < 1      → smoothstep 过渡
        L = 1.0              → 输出 = 输入
    两条交付路径（创意配置文件 / 直接套图）必须用同一个 protect，否则色调契约不一致。
    """
    if protect <= 0.0:
        return out
    lum = (0.2126 * base[..., 0] + 0.7152 * base[..., 1] + 0.0722 * base[..., 2])
    t = np.clip((lum - protect) / max(1e-6, 1.0 - protect), 0.0, 1.0)
    w = 1.0 - (t * t * (3.0 - 2.0 * t))
    return out * w[..., None] + base * (1.0 - w[..., None])


def backup_path_for(path: str) -> str:
    """原地覆盖前的备份位置：与源文件同目录的 .filmsim-backups/，带时间戳，不覆盖旧备份。"""
    d = os.path.join(os.path.dirname(os.path.abspath(path)), ".filmsim-backups")
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(d, f"{os.path.basename(path)}.{ts}.bak")


def process_one(path: str, lut, lut1d, args) -> tuple:
    """返回 (target, backup_or_None)。原地模式必定先备份；--out 模式拒绝静默覆盖。"""
    arr, kind = read_image(path)
    meta = None
    if isinstance(kind, tuple):
        kind, meta = kind
    if arr.ndim == 2:  # 灰度
        rgb = np.repeat(arr[:, :, None], 3, axis=2)
        gray = True
    else:
        rgb = arr[:, :, :3]
        gray = False
    f, scale = to_float(rgb)
    res = apply_lut(f, lut, lut1d, args.strength, args.linear_pipeline, args.pre_gain)
    res = protect_blend(res, f, args.protect)
    res = from_float(res, scale)
    if gray:
        res = res[:, :, 0]

    backup = None
    if args.in_place:
        target = path
        if not args.no_backup:
            backup = backup_path_for(path)
            shutil.copy2(path, backup)
    else:
        os.makedirs(args.out, exist_ok=True)
        base = os.path.basename(path)
        stem, ext = os.path.splitext(base)
        target = os.path.join(args.out, f"{stem}{args.suffix}{ext}")
        # 不静默覆盖：输出目录里已有同名文件时必须显式 --overwrite
        if os.path.exists(target) and os.path.abspath(target) != os.path.abspath(path):
            if not args.overwrite:
                raise FileExistsError(
                    f"输出已存在：{target}（加 --overwrite 才允许覆盖，或换 --out 目录）")
    write_image(target, res, kind if kind == "tiff" else "pil", meta)
    return target, backup


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="应用 .cube / HaldCLUT 胶片模拟 LUT")
    ap.add_argument("--lut", required=True, help=".cube 或 HaldCLUT PNG")
    ap.add_argument("--out", help="输出目录。**默认必须提供**：不写 --out 就必须显式写 --in-place")
    ap.add_argument("--in-place", action="store_true",
                    help="原地改写输入文件。破坏性操作，必须显式指定；默认会先写时间戳备份")
    ap.add_argument("--no-backup", action="store_true",
                    help="原地模式下不写备份（不推荐；只有调用方自己保证有副本时才用）")
    ap.add_argument("--overwrite", action="store_true",
                    help="允许覆盖 --out 目录里已存在的同名输出（默认拒绝）")
    ap.add_argument("--calibration", default=None,
                    help="calibrate-luts.py 产出的 JSON：按 LUT 文件名取该卷自己的 pre-gain")
    ap.add_argument("--protect", type=float, default=0.0,
                    help="护高光阈值 0~1。必须与生成创意配置文件时用的值一致，"
                         "否则两条路径的色调契约不一致（0=不护）")
    ap.add_argument("--suffix", default="_filmsim", help="--out 模式下的文件名后缀")
    ap.add_argument("--strength", type=float, default=1.0, help="混合强度 0~1")
    ap.add_argument("--linear-pipeline", action="store_true",
                    help="LUT 是 linear→linear 时加此开关（先解码 sRGB，套 LUT 后再编码）")
    ap.add_argument("--pre-gain", type=float, default=1.0,
                    help="线性域预增益。spektrafilm 默认 bundle 把源白点放在 +4 档，"
                         "直接套会亮约 1.5 档；用 0.35 可把中灰放回原位")
    ap.add_argument("--info", action="store_true", help="只打印 LUT 信息")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)

    if not os.path.exists(args.lut):
        print(f"[lr-filmsim] LUT 不存在：{args.lut}", file=sys.stderr)
        return 2

    bad = []
    if not (0.0 <= args.strength <= 1.0):
        bad.append(f"--strength {args.strength}（要求 0–1）")
    if not (0.0 <= args.protect < 1.0):
        bad.append(f"--protect {args.protect}（要求 0 ≤ protect < 1）")
    if not (0.01 <= args.pre_gain <= 8.0):
        bad.append(f"--pre-gain {args.pre_gain}（要求 0.01–8.0）")
    if bad:
        print("[lr-filmsim] 参数越界，已中止：", file=sys.stderr)
        for b in bad:
            print(f"    {b}", file=sys.stderr)
        return 2

    # 安全默认：必须显式选择落盘位置。缺省原地改写是过去的行为，会导致用户原图被覆盖。
    if args.out and args.in_place:
        print("[lr-filmsim] --out 与 --in-place 互斥，请只选一个", file=sys.stderr)
        return 2
    if not args.out and not args.in_place:
        print("[lr-filmsim] 未指定输出位置。请二选一：\n"
              "  --out <目录>     写入新目录（推荐，不动原图）\n"
              "  --in-place       原地改写（会先写备份，需你明确确认）", file=sys.stderr)
        return 2
    if args.in_place and args.no_backup:
        print("[lr-filmsim] 警告：--in-place --no-backup 会不可逆地覆盖原图", file=sys.stderr)

    # 逐卷标定：按 LUT 文件名取该卷自己的 pre-gain（不再共用固定系数）
    if args.calibration:
        if not os.path.exists(args.calibration):
            print(f"[lr-filmsim] 标定文件不存在：{args.calibration}", file=sys.stderr)
            return 2
        cal = json.loads(open(args.calibration, encoding="utf-8").read())
        key = os.path.splitext(os.path.basename(args.lut))[0]
        entry = cal.get(key)
        if entry is None:
            print(f"[lr-filmsim] 标定文件里没有 {key!r} 这一条（共 {len(cal)} 条）；"
                  f"请对当前 LUT 重新标定", file=sys.stderr)
            return 2
        cal_protect = float(entry.get("protect", 0.0))
        if "protect" in entry and abs(cal_protect - args.protect) > 1e-9:
            print(f"[lr-filmsim] 护高光阈值不一致：标定时 protect={cal_protect}，"
                  f"本次 --protect {args.protect}。两条路径必须同口径；"
                  f"改 --protect {cal_protect} 或重新标定。", file=sys.stderr)
            return 2
        args.pre_gain = float(entry["pre_gain"])
        print(f"[lr-filmsim] 用标定值 pre-gain={args.pre_gain}（来自 {args.calibration} 的 {key}）")

    lut, lut1d = load_lut(args.lut)
    n = lut.shape[0]
    if args.info:
        print(f"LUT: {args.lut}")
        print(f"  3D 网格: {n}^3 = {n**3} 项, 范围 [0,1]")
        print(f"  1D shaper: {'有, ' + str(lut1d.shape[0]) + ' 项' if lut1d is not None else '无'}")
        return 0

    if not args.files:
        print("[lr-filmsim] 没有输入文件", file=sys.stderr)
        return 2

    rc = 0
    for p in args.files:
        if not os.path.exists(p):
            print(f"[lr-filmsim] 跳过（不存在）：{p}", file=sys.stderr)
            rc = 1
            continue
        try:
            tgt, bak = process_one(p, lut, lut1d, args)
            print(f"[lr-filmsim] {p} -> {tgt}" + (f"（原图备份：{bak}）" if bak else ""))
        except Exception as exc:  # noqa: BLE001
            print(f"[lr-filmsim] 失败 {p}: {exc}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
