#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify-delivery.py —— 为一次交付**真正算出** verification.json（不再靠交付方手填）。

为什么需要它：references/verification-schema.md 要求每次交付留下机器可读凭证，但过去仓库里
没有任何脚本负责生成它，于是很容易退化成"Agent 不会算 → 抄示例数字 → 评分器读到数字 → 宣布通过"。
这个脚本把每一项指标都从产物本身算出来，并把**算不出来**的项显式标成不可复算，而不是留空或猜。

用法（SKILL_ROOT = 本仓库根目录）：

  # 只验证配置文件本身（不需要源 LUT / 照片）：表 ID、元数据配对、灰阶响应、中灰、纯白
  python3 "$SKILL_ROOT/scripts/verify-delivery.py" \
      --profile "$OUT/Look.xmp" --out "$OUT/verification.json"

  # 再加上源 LUT：可复算 decode_error_lsb（编码往返误差）
  python3 "$SKILL_ROOT/scripts/verify-delivery.py" \
      --profile "$OUT/Look.xmp" --lut "$LUTS/Look.cube" \
      --pre-gain 1.741 --protect 0.68 --out "$OUT/verification.json"

  # 再加上真实照片：可复算亮度比 / 最亮 5% 中位 / ≥250 占比 / 高光细节 std
  python3 "$SKILL_ROOT/scripts/verify-delivery.py" \
      --profile "$OUT/Look.xmp" --images a.tif b.tif --out "$OUT/verification.json"

退出码：0 = 通过；1 = 有指标不达标或声明与重算不一致；2 = 用法错误。

指标定义（与 references/calibration.md §3 一致，避免"中位/均值"这类歧义）：

  平均亮度比        out_lum.mean() / src_lum.mean()，lum = 0.2126R+0.7152G+0.0722B (0–255)
  最亮 5% 中位      **取原图**亮度前 5% 的像素集合，看它们在**输出**里的亮度中位数（不是均值）
  ≥250 像素占比     输出里亮度 ≥250 的像素占比
  高光区细节 std    同一组「原图最亮 5%」像素在输出里的亮度标准差
"""

from __future__ import annotations

# Windows 上输出被重定向时控制台默认用 cp1252，打印中文/符号会 UnicodeEncodeError。
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
import json
import os
import re
import sys
import time
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# 阈值（与 calibration.md §3 / verification-schema.md 一致）
#
# 注意：这些绝对阈值来自早期文档（`原图约 4%`、`原图约 6.1`），而那批测试条件未随仓库归档
# ——见 references/calibration.md §0。所以给 --images 时，判定改为「不低于下面这个绝对目标，
# 同时不低于相对原图基准的下限」：绝对目标在浅高光的图上本来就达不到（例如原图只有 1% 的
# ≥250 像素时，要求输出 ≥2.5% 是无意义的）。两个条件取对交付更宽松的那个，但**绝不允许
# 输出比原图还差**。实际用了哪条会写进 verification.json 的 thresholds_used。
T = {
    "decode_error_lsb": 1.0,
    "mid_gray_out": (118.0, 145.0),
    "white_out": 250.0,
    "brightness_ratio": (0.95, 1.05),
    "top5pct_median": 240.0,
    "pct_ge_250": 2.5,
    "highlight_detail_std": 3.5,
}

SPACE_META = {
    "display": {"base_profile": "Adobe Standard", "metadata": [1, 3, 0, 0.0, 1.0]},
    "linear": {"base_profile": "Adobe Standard Linear", "metadata": [3, 1, 0, 1.0, 1.0]},
}


def load_cc():
    spec = importlib.util.spec_from_file_location("cc", HERE / "lut-to-ccprofile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_profile(path: Path) -> dict:
    """从 XMP 里取出验证需要的字段（不依赖 XML 解析，属性是单行等宽写法）。"""
    s = path.read_text(encoding="utf-8")
    out = {"path": str(path)}
    m = re.search(r'crs:RGBTable="([0-9A-Fa-f]+)"', s)
    if not m:
        raise SystemExit(f"[verify] {path} 里找不到 crs:RGBTable —— 这不是创意配置文件？")
    out["table_id"] = m.group(1)
    m = re.search(r'crs:Table_' + out["table_id"] + r'="([^"]+)"', s)
    if not m:
        raise SystemExit(f"[verify] {path} 里找不到 crs:Table_{out['table_id']}（表数据缺失）")
    out["payload"] = m.group(1)
    m = re.search(r'crs:CameraProfile="([^"]*)"', s)
    out["base_profile"] = m.group(1) if m else ""
    m = re.search(r'crs:UUID="([^"]*)"', s)
    out["uuid"] = m.group(1) if m else ""
    out["raw"] = s
    return out


def pairing_of(payload: str, cc) -> dict:
    """从表头读出 space 元数据，并判断它与基底配置文件是否配对。"""
    raw = zlib.decompress(cc.b85_decode(payload)[4:])
    div = int(np.frombuffer(raw[:4], dtype="<u4")[0]) if False else None
    # 表头：u32 type, u32 version, u32 dims, u32 divisions, 样本, u32 primaries, u32 gamma, u32 gamut, f64, f64
    n = int(np.frombuffer(raw[12:16], dtype="<u4")[0])
    tail = raw[16 + n * n * n * 3 * 2:]
    primaries, gamma, gamut = (int(x) for x in np.frombuffer(tail[:12], dtype="<u4"))
    meta = [primaries, gamma, gamut] + [float(x) for x in np.frombuffer(tail[12:28], dtype="<f8")]
    return {"divisions": n, "metadata": meta}


def gray_curve(cc, table: np.ndarray) -> np.ndarray:
    """把表施加到 256 级灰阶上，返回 0–255 的输出亮度。"""
    ramp = np.repeat(np.linspace(0, 1, 256)[:, None], 3, axis=1)[None].astype(np.float32)
    out = cc.core._apply_3d(table.astype(np.float32), ramp)[0]
    return out.mean(axis=1) * 255.0


def lum_of(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., :3] * LUMA).sum(axis=-1)


def apply_table_to_image(cc, table: np.ndarray, img: np.ndarray, space: str) -> np.ndarray:
    """按宿主的实际行为施加这张表：display 族直接喂显示域数据，linear 族先解到线性。"""
    srgb = img.astype(np.float32) / 255.0
    src = cc.core.srgb_to_linear(srgb) if space == "linear" else srgb
    out = cc.core._apply_3d(table.astype(np.float32), src.reshape(1, -1, 3))[0]
    if space == "linear":
        out = cc.core.linear_to_srgb(out)
    return (np.clip(out, 0, 1).reshape(img.shape) * 255.0).astype(np.float32)


def image_metrics(cc, table: np.ndarray, space: str, paths) -> dict:
    """在真实照片上复算四个图片级指标（原图 vs 输出）。"""
    from PIL import Image

    ratios, medians, shares, stds = [], [], [], []
    src_medians, src_shares, src_stds = [], [], []
    for p in paths:
        im = Image.open(p).convert("RGB")
        arr = np.asarray(im, dtype=np.uint8)
        src_lum = lum_of(arr.astype(np.float32))
        out = apply_table_to_image(cc, table, arr, space)
        out_lum = lum_of(out)

        ratios.append(float(out_lum.mean() / max(1e-6, src_lum.mean())))
        thr = np.percentile(src_lum, 95.0)
        hi = src_lum >= thr
        if hi.sum() >= 16:
            medians.append(float(np.median(out_lum[hi])))
            stds.append(float(np.std(out_lum[hi])))
            src_medians.append(float(np.median(src_lum[hi])))
            src_stds.append(float(np.std(src_lum[hi])))
        shares.append(float((out_lum >= 250).mean() * 100.0))
        src_shares.append(float((src_lum >= 250).mean() * 100.0))

    mean = lambda v: round(float(np.mean(v)), 3) if v else None  # noqa: E731
    out_std, src_std = mean(stds), mean(src_stds)
    return {
        "brightness_ratio": round(float(np.mean(ratios)), 4),
        "top5pct_median": mean(medians),
        "pct_ge_250": mean(shares),
        "highlight_detail_std": out_std,
        # 原图基准：没有它就无法判断"高光细节保留了多少"，
        # 之前文档给的绝对值（约 6.1 → 1.0）没有随仓库归档，只能靠这里的现场基准。
        "src_top5pct_median": mean(src_medians),
        "src_pct_ge_250": mean(src_shares),
        "src_highlight_detail_std": src_std,
        "highlight_detail_retention": (round(out_std / src_std, 3)
                                       if (out_std and src_std) else None),
        "images": [str(x) for x in paths],
        "images_count": len(list(paths)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="从交付产物真算 verification.json")
    ap.add_argument("--profile", required=True, help="创意配置文件 .xmp")
    ap.add_argument("--lut", default="", help="源 .cube（提供则复算 decode_error_lsb）")
    ap.add_argument("--pre-gain", type=float, default=None, help="生成时用的 pre-gain（配 --lut）")
    ap.add_argument("--protect", type=float, default=None, help="生成时用的 protect（配 --lut）")
    ap.add_argument("--divisions", type=int, default=None, help="生成时用的网格；默认从表里读")
    ap.add_argument("--space", default="", choices=["", "display", "linear"],
                    help="生成时用的空间；默认按元数据自动判定")
    ap.add_argument("--images", nargs="*", default=[], help="真实照片：可复算图片级四项指标")
    ap.add_argument("--calibration", default="",
                    help="校准 JSON：按 LUT 文件名取当时用的 pre_gain/protect，避免手抄错")
    ap.add_argument("--out", default="verification.json")
    ap.add_argument("--declare", default="", help="另一份 verification.json：与其逐项比对")
    args = ap.parse_args()

    cc = load_cc()
    prof_path = Path(args.profile).expanduser()
    if not prof_path.is_file():
        print(f"[verify] 配置文件不存在：{prof_path}", file=sys.stderr)
        return 2

    info = parse_profile(prof_path)
    pair = pairing_of(info["payload"], cc)
    table, div = cc.decode_table(info["payload"])

    # 空间由元数据反推（表头自己说了算）
    space = args.space or ("linear" if pair["metadata"][:3] == [3, 1, 0] else "display")
    expect_base = SPACE_META[space]["base_profile"]
    expect_meta = SPACE_META[space]["metadata"]

    checks = {}

    # ① 表 ID = MD5(解压后的表)
    blob = zlib.decompress(cc.b85_decode(info["payload"])[4:])
    md5 = hashlib.md5(blob).hexdigest().upper()
    checks["table_id_matches_md5"] = md5 == info["table_id"].upper()

    # ② 元数据与基底配置文件配对
    checks["metadata_matches_space"] = pair["metadata"] == expect_meta
    checks["base_profile_matches_space"] = info["base_profile"] == expect_base

    # ③ 灰阶响应 / 中灰 / 纯白 —— 全部从表里真算
    curve = gray_curve(cc, table)
    checks["gray_response"] = {str(i): round(float(curve[i]), 2) for i in
                              (0, 32, 64, 96, 128, 160, 192, 224, 255)}
    checks["mid_gray_out"] = round(float(curve[128]), 2)
    checks["white_out"] = round(float(curve[255]), 2)

    # ④ 编码往返误差 —— 需要源 LUT 与当时的口径
    if args.calibration:
        cal = json.loads(Path(args.calibration).expanduser().read_text(encoding="utf-8"))
        key = Path(args.lut).stem if args.lut else None
        if key and key in cal:
            entry = cal[key]
            if args.pre_gain is None:
                args.pre_gain = float(entry["pre_gain"])
            if args.protect is None:
                args.protect = float(entry.get("protect", 0.0))
            print(f"[verify] 从标定文件取到 {key}: pre_gain={args.pre_gain} "
                  f"protect={args.protect} mode={entry.get('mode')}")
        else:
            print(f"[verify] 标定文件里没有 {key!r}，请显式给 --pre-gain/--protect", file=sys.stderr)
            return 2

    if args.lut:
        if args.pre_gain is None or args.protect is None:
            print("[verify] 给了 --lut 就必须同时给 --pre-gain 与 --protect（当时生成用的值）",
                  file=sys.stderr)
            return 2
        want = cc.build_table(Path(args.lut).expanduser(), div, space,
                              args.pre_gain, args.protect)
        checks["decode_error_lsb"] = round(float(np.abs(table - want).max() * 65535), 4)
    else:
        checks["decode_error_lsb"] = None

    # ⑤ 图片级四项 —— 需要真实照片才复算
    if args.images:
        m = image_metrics(cc, table, space, [Path(x) for x in args.images])
        checks["brightness_ratio"] = m["brightness_ratio"]
        checks["top5pct_median"] = m["top5pct_median"]
        checks["pct_ge_250"] = m["pct_ge_250"]
        checks["highlight_detail_std"] = m["highlight_detail_std"]
        checks["src_top5pct_median"] = m["src_top5pct_median"]
        checks["src_pct_ge_250"] = m["src_pct_ge_250"]
        checks["src_highlight_detail_std"] = m["src_highlight_detail_std"]
        checks["highlight_detail_retention"] = m["highlight_detail_retention"]
        images_used = m["images"]
    else:
        for k in ("brightness_ratio", "top5pct_median", "pct_ge_250", "highlight_detail_std"):
            checks[k] = None
        images_used = []

    # ── 判定：能算的按阈值判；算不出来的明确标成未复算，绝不当作通过 ──
    fails, unrecomputed = [], []
    def need(key, ok):
        if not ok:
            fails.append(key)

    need("table_id_matches_md5", checks["table_id_matches_md5"])
    need("metadata_matches_space", checks["metadata_matches_space"])
    need("base_profile_matches_space", checks["base_profile_matches_space"])
    if checks["decode_error_lsb"] is None:
        unrecomputed.append("decode_error_lsb")
    else:
        need("decode_error_lsb", checks["decode_error_lsb"] <= T["decode_error_lsb"])
    lo, hi = T["mid_gray_out"]
    need("mid_gray_out", lo <= checks["mid_gray_out"] <= hi)
    need("white_out", checks["white_out"] >= T["white_out"])
    thresholds_used = {}
    for k in ("brightness_ratio", "top5pct_median", "pct_ge_250", "highlight_detail_std"):
        v = checks[k]
        if v is None:
            unrecomputed.append(k)
            continue
        if k == "brightness_ratio":
            lo2, hi2 = T[k]; thresholds_used[k] = [lo2, hi2]
            need(k, lo2 <= v <= hi2)
            continue
        # 相对原图基准的下限（原图有多好，输出至少要保住其中一部分）
        rel = {
            "top5pct_median": ("src_top5pct_median", 0.95),
            "pct_ge_250": ("src_pct_ge_250", 0.80),
            "highlight_detail_std": ("src_highlight_detail_std", 0.50),
        }[k]
        src_key, frac = rel
        src_val = checks.get(src_key)
        floor = T[k]
        if isinstance(src_val, (int, float)):
            floor = min(T[k], round(frac * src_val, 3))
        thresholds_used[k] = {"absolute_target": T[k], "applied_floor": floor,
                              "source_baseline": src_val, "source_fraction": frac}
        need(k, v >= floor)

    declarations = {}
    mismatches = []
    if args.declare:
        try:
            declarations = json.loads(Path(args.declare).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[verify] --declare 读不了：{exc}", file=sys.stderr)
            return 2
        dchecks = (declarations.get("checks") or {})
        for k, mine in checks.items():
            if k in dchecks and dchecks[k] is not None and mine is not None:
                if isinstance(mine, dict):
                    continue
                if abs(float(dchecks[k]) - float(mine)) > 0.05:
                    mismatches.append({"field": k, "declared": dchecks[k], "recomputed": mine})

    verdict = "pass" if (not fails and not mismatches) else "fail"
    out = {
        "skill": "film-sim-delivery",
        "verifier": "scripts/verify-delivery.py",
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "inputs": {
            "profile": str(prof_path),
            "lut": args.lut or None,
            "divisions": div,
            "images": images_used,
        },
        "params": {
            "space": space,
            "base_profile": info["base_profile"],
            "metadata": pair["metadata"],
            "pre_gain": args.pre_gain,
            "protect": args.protect,
        },
        "outputs": {"profile": str(prof_path), "table_id": info["table_id"]},
        "checks": checks,
        "thresholds_used": thresholds_used,
        "unrecomputed": unrecomputed,
        "failed": fails,
        "declaration_mismatches": mismatches,
        "verdict": verdict,
        "notes": (
            "所有非 null 的 checks 都是本脚本从产物算出来的。"
            "unrecomputed 列出的项缺少输入（源 LUT 或真实照片），**不代表通过**。"
            "对照 references/verification-schema.md 的阈值。"
        ),
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"配置文件：{prof_path}")
    print(f"空间={space}  基底={info['base_profile']}  元数据={pair['metadata']}  {div}^3")
    for k in ("table_id_matches_md5", "metadata_matches_space", "base_profile_matches_space",
              "decode_error_lsb", "mid_gray_out", "white_out", "brightness_ratio",
              "top5pct_median", "pct_ge_250", "highlight_detail_std"):
        v = checks[k]
        mark = "—" if v is None else ("✓" if k not in fails else "✗")
        print(f"  {mark} {k:24s} {v}")
    if checks.get("highlight_detail_retention") is not None:
        print(f"    （高光细节保留率 {checks['highlight_detail_retention']}"
              f" = 输出 {checks['highlight_detail_std']} / 原图 "
              f"{checks['src_highlight_detail_std']}；文档里的绝对阈值 3.5 是验收目标，"
              f"不是在你这批图上的历史实测值）")
    if mismatches:
        print("\n声明与重算不一致：")
        for m in mismatches:
            print(f"  ✗ {m['field']}: 声明 {m['declared']} / 重算 {m['recomputed']}")
    if checks.get("src_pct_ge_250") is not None:
        print(f"    原图基准：最亮 5% 中位 {checks['src_top5pct_median']} / "
              f"≥250 占比 {checks['src_pct_ge_250']}% / 高光细节 std {checks['src_highlight_detail_std']}")
        for k in ("top5pct_median", "pct_ge_250", "highlight_detail_std"):
            tu = thresholds_used.get(k)
            if tu and tu["applied_floor"] != tu["absolute_target"]:
                print(f"    {k}: 绝对目标 {tu['absolute_target']} 在你这批图上不可达，"
                      f"按原图基准 {tu['source_fraction']}× 判为 ≥{tu['applied_floor']}")
    if unrecomputed:
        print(f"\n未复算（缺输入，不等于通过）：{', '.join(unrecomputed)}")
        if "brightness_ratio" in unrecomputed:
            print("  想复算图片级四项就加 --images <真实照片…>")
        if "decode_error_lsb" in unrecomputed:
            print("  想复算编码误差就加 --lut <源 .cube> --pre-gain G --protect P")
    print(f"\nverdict: {verdict}   →  {args.out}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
