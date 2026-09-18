#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grade.py (v2) —— **只读产物**的评分器。

不再用关键词匹配报告文本；改为要求产物里包含
  * verification.json（交付凭证，见 references/verification-schema.md）
  * diagnosis.json（诊断任务：root_cause_code + evidence）
并**独立重算**关键数字（解出 RGBTable、算灰阶响应）与声明值比对 ——
"写了数字但没真算"会被抓出来。

用法： python3 evals/grade.py <run-dir> --eval 0|1|2 [--json out.json]
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

import argparse, glob, hashlib, importlib.util, json, os, re, struct, zlib
from pathlib import Path

import numpy as np

SKILL_ROOT = Path(__file__).resolve().parent.parent
LEVELS = [0, 32, 64, 96, 128, 160, 192, 224, 255]
TOL_GRAY = 1.5


def load_cc():
    spec = importlib.util.spec_from_file_location("cc", SKILL_ROOT / "scripts" / "lut-to-ccprofile.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    return cc


def find_json(run_dir: Path, name: str):
    hits = [h for h in glob.glob(str(run_dir / "**" / name), recursive=True) if "/.venv/" not in h]
    if not hits:
        return None, None
    p = Path(sorted(hits, key=lambda x: (len(x), x))[0])
    try:
        return json.loads(p.read_text(encoding="utf-8")), p
    except Exception:
        return None, p


def find_profiles(run_dir: Path, kind: str = "look"):
    out = []
    for f in glob.glob(str(run_dir / "**" / "*.xmp"), recursive=True):
        base = os.path.basename(f)
        if "/.venv/" in f or "自检" in base or "selftest" in base.lower():
            continue
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if kind == "look" and "crs:Table_" in txt and "crs:RGBTable" in txt:
            out.append((Path(f), txt))
        elif kind == "wrapper" and "crs:Look" in txt and "crs:Table_" not in txt:
            out.append((Path(f), txt))
    return out


def parse_profile(path: Path, txt: str, cc) -> dict:
    tid = re.search(r'crs:RGBTable="([0-9A-Fa-f]+)"', txt).group(1)
    payload = re.search(r'crs:Table_' + tid + r'="([^"]+)"', txt).group(1)
    table, div = cc.decode_table(payload)
    data = zlib.decompress(cc.b85_decode(payload)[4:])
    meta = struct.unpack_from("<IIIdd", data, 16 + div ** 3 * 6)
    base = re.search(r'crs:CameraProfile="([^"]*)"', txt)
    uuid = re.search(r'crs:UUID="([0-9A-Fa-f]+)"', txt)
    return {"path": path, "table": table, "div": div, "meta": tuple(meta),
            "base": base.group(1) if base else None,
            "uuid": uuid.group(1).upper() if uuid else None,
            "table_id": tid.upper(),
            "actual_md5": hashlib.md5(data).hexdigest().upper()}


def gray_response(cc, ps: dict) -> dict:
    ramp = np.array(LEVELS, dtype=np.float32) / 255.0
    pts = np.repeat(ramp[:, None], 3, axis=1)[None]
    out = cc.core._apply_3d(ps["table"].astype(np.float32), pts)[0].mean(axis=1) * 255
    return {str(l): round(float(v), 1) for l, v in zip(LEVELS, out)}


def pairing_ok(ps: dict) -> bool:
    return ((ps["meta"] == (1, 3, 0, 0.0, 1.0) and ps["base"] == "Adobe Standard")
            or (ps["meta"] == (3, 1, 0, 1.0, 1.0) and ps["base"] == "Adobe Standard Linear"))


def _score_candidate(cc, item):
    try:
        ps = parse_profile(item[0], item[1], cc)
        r = gray_response(cc, ps)
        return ((2 if 118 <= (r.get("128") or 0) <= 145 else 0)
                + (2 if pairing_ok(ps) else 0)
                + (2 if float(r.get("255", 0)) >= 250 else 0))
    except Exception:
        return -1


def _best_candidate(cc, looks):
    return max(looks, key=lambda it: _score_candidate(cc, it)) if looks else None


def grade(run_dir: Path, eval_id: int, fixtures_dir: Path | None = None) -> dict:
    cc = load_cc()
    results = []

    def add(text, passed, evidence=""):
        results.append({"text": text, "passed": bool(passed), "evidence": str(evidence)})

    ver, ver_path = find_json(run_dir, "verification.json")
    diag, _ = find_json(run_dir, "diagnosis.json")
    looks = find_profiles(run_dir, "look")
    wrappers = find_profiles(run_dir, "wrapper")

    add("存在 verification.json 且可解析", ver is not None, ver_path or "未找到")

    if eval_id == 0:
        add("产出内嵌 RGBTable 的配置文件", bool(looks), f"{len(looks)} 个候选")
        target = _best_candidate(cc, looks)
        if not target:
            for t in ["表可独立解码", "表 ID = 表内容 MD5", "元数据/基底配对正确",
                      "中灰落在 118–145", "纯白 ≥250（护高光生效）",
                      "声明的灰阶与独立重算一致", "checks.decode_error_lsb ≤1.0",
                      "checks.brightness_ratio 0.95–1.05", "高光三项达标",
                      "wrapper 存在且 UUID 匹配"]:
                add(t, False, "无产物")
            return {"eval_id": eval_id, "assertions": results}

        ps = parse_profile(target[0], target[1], cc)
        resp = gray_response(cc, ps)
        add("表可独立解码", True, f"{ps['path'].name}: {ps['div']}³")
        add("表 ID = 表内容 MD5", ps["table_id"] == ps["actual_md5"],
            f"声明 {ps['table_id'][:12]}… 实算 {ps['actual_md5'][:12]}…")
        add("元数据/基底配对正确", pairing_ok(ps), f"meta={ps['meta']} base={ps['base']}")
        mid = resp.get("128")
        add("中灰落在 118–145", mid is not None and 118 <= mid <= 145, f"128 → {mid}")
        add("纯白 ≥250（护高光生效）", float(resp.get("255", 0)) >= 250, f"255 → {resp.get('255')}")

        claimed = (ver or {}).get("checks", {}).get("gray_response") if ver else None
        if claimed:
            diffs = [abs(float(claimed[k]) - resp[k]) for k in resp if k in claimed]
            add("声明的灰阶与独立重算一致", bool(diffs) and max(diffs) <= TOL_GRAY,
                f"最大差 {max(diffs):.2f}/255（比了 {len(diffs)} 档）" if diffs else "无可比字段")
        else:
            add("声明的灰阶与独立重算一致", False, "缺 checks.gray_response")

        c = (ver or {}).get("checks", {})
        add("checks.decode_error_lsb ≤1.0",
            isinstance(c.get("decode_error_lsb"), (int, float)) and c["decode_error_lsb"] <= 1.0,
            f"声明 {c.get('decode_error_lsb')}")
        add("checks.brightness_ratio 0.95–1.05",
            isinstance(c.get("brightness_ratio"), (int, float))
            and 0.95 <= c["brightness_ratio"] <= 1.05, f"声明 {c.get('brightness_ratio')}")
        add("高光三项达标",
            isinstance(c.get("top5pct_median"), (int, float)) and c["top5pct_median"] >= 240
            and isinstance(c.get("pct_ge_250"), (int, float)) and c["pct_ge_250"] >= 2.5
            and isinstance(c.get("highlight_detail_std"), (int, float))
            and c["highlight_detail_std"] >= 3.5,
            f"top5%={c.get('top5pct_median')} ≥250={c.get('pct_ge_250')} 细节={c.get('highlight_detail_std')}")
        add("checks.mid_gray_out / white_out 与重算一致",
            isinstance(c.get("mid_gray_out"), (int, float))
            and abs(c["mid_gray_out"] - (mid or 0)) <= TOL_GRAY
            and isinstance(c.get("white_out"), (int, float))
            and abs(c["white_out"] - float(resp.get("255", 0))) <= TOL_GRAY,
            f"声明 mid={c.get('mid_gray_out')} white={c.get('white_out')}")
        w_ok = False
        for _, wtxt in wrappers:
            m = re.search(r'crs:Look[^>]*crs:UUID="([0-9A-Fa-f]+)"', wtxt, re.S)
            if m and ps["uuid"] and m.group(1).upper() == ps["uuid"]:
                w_ok = True
                break
        add("wrapper 存在且 UUID 匹配", w_ok, f"{len(wrappers)} 个 wrapper")

    else:
        code = str((diag or {}).get("root_cause_code") or "")
        cl = code.lower()
        if eval_id == 1:
            ok_code = (any(t in cl for t in ("space", "domain", "family", "metadata", "基底", "元数据"))
                       and any(t in cl for t in ("mismatch", "mismat", "wrong", "conflict", "不匹配", "错配")))
            expect_txt = "空间/族/元数据 与声明不匹配"
        else:
            ok_code = (any(t in cl for t in ("highlight", "protect", "shoulder", "clip", "护高光", "肩部"))
                       and not any(t in cl for t in ("space", "domain", "family", "metadata")))
            expect_txt = "护高光缺失/肩部封顶"
        add(f"root_cause_code 指向正确根因（{expect_txt}）", ok_code, f"实际 {code!r}")

        # evidence：不限字段名，只要求"出现了正确量级的数字"，并与独立复核一致
        ev = (diag or {}).get("evidence", {})
        nums = []

        def walk(o):
            if isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, (int, float)):
                nums.append(float(o))

        walk(ev)
        bad_white = None
        bps = None
        if fixtures_dir:
            bad_path = fixtures_dir / ("bad/portra_spacemismatch.xmp" if eval_id == 1
                                       else "bad/portra_noprotect.xmp")
            lut_path = fixtures_dir / "luts/portra_like.cube"
            if bad_path.exists():
                try:
                    bps = parse_profile(bad_path, bad_path.read_text(encoding="utf-8", errors="ignore"), cc)
                    bad_white = float(gray_response(cc, bps).get("255", -1))
                except Exception:  # noqa: BLE001
                    bps = None
            if eval_id == 1:
                if bps is not None and lut_path.exists():
                    lin = float(np.abs(cc.build_table(lut_path, bps["div"], "linear", 0.3472, 0.0)
                                       - bps["table"]).max()) * 65535
                    disp = float(np.abs(cc.build_table(lut_path, bps["div"], "display", 0.3472, 0.0)
                                        - bps["table"]).max()) * 65535
                    add("独立复核：坏样本 ≈ 线性族、≠ 显示族", lin <= 1.0 and disp > 1000,
                        f"linear={lin:.1f} display={disp:.1f} /65535")
                else:
                    add("独立复核：坏样本 ≈ 线性族、≠ 显示族", False, "缺 fixture 或 LUT")
                add("evidence 含族比对数值（一个 ≤2，一个 >1000）",
                    any(v <= 2.0 for v in nums) and any(v > 1000 for v in nums),
                    f"数字 {len(nums)} 个，max={max(nums) if nums else None}")
            else:
                add("独立复核：坏样本纯白确实 ≤215（肩部封顶）",
                    bad_white is not None and bad_white <= 215, f"实测 {bad_white}")
                add("evidence 含修复前后纯白数值（≤215 与 ≥250）",
                    any(v <= 215 for v in nums) and any(v >= 250 for v in nums),
                    f"数字 {len(nums)} 个")
        else:
            add("独立复核坏样本", False, "未提供 --fixtures")

        fixed = _best_candidate(cc, looks)
        ps = None
        if fixed:
            try:
                ps = parse_profile(fixed[0], fixed[1], cc)
            except Exception as exc:  # noqa: BLE001
                ps = None
                add("交付文件按 Adobe 约定可解码", False,
                    f"{fixed[0].name} 解码失败：{type(exc).__name__}: {str(exc)[:60]}")
        add("产出可解码的修复后配置", ps is not None,
            f"{len(looks)} 个候选" if looks else "未找到")
        if ps is not None:
            resp = gray_response(cc, ps)
            resp = gray_response(cc, ps)
            add("修复后纯白 ≥250", float(resp.get("255", 0)) >= 250, f"255 → {resp.get('255')}")
            add("修复后中灰仍在 118–145",
                resp.get("128") is not None and 118 <= resp["128"] <= 145, f"128 → {resp.get('128')}")
            add("修复后元数据/基底配对正确", pairing_ok(ps), f"meta={ps['meta']} base={ps['base']}")
            claimed = (ver or {}).get("checks", {}).get("gray_response") if ver else None
            if claimed:
                diffs = [abs(float(claimed[k]) - resp[k]) for k in resp if k in claimed]
                add("verification.json 的 checks 与独立重算一致",
                    bool(diffs) and max(diffs) <= TOL_GRAY,
                    f"最大差 {max(diffs):.2f}/255" if diffs else "无可比字段")
            else:
                add("verification.json 的 checks 与独立重算一致", False, "缺 checks.gray_response")
        else:
            for t in ["修复后纯白 ≥250", "修复后中灰仍在 118–145",
                      "修复后元数据/基底配对正确", "verification.json 的 checks 与独立重算一致"]:
                add(t, False, "无产物")

    return {"eval_id": eval_id, "run_dir": str(run_dir), "assertions": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--eval", dest="eval_id", type=int, required=True)
    ap.add_argument("--json", default="")
    ap.add_argument("--fixtures", default="",
                    help="评测样本目录（含 bad/ 与 luts/），用于独立复核。"
                         "默认用仓库自带的 evals/fixtures")
    ap.add_argument("--no-fixtures", action="store_true",
                    help="跳过坏样本独立复核（样本目录缺失时用）")
    args = ap.parse_args()

    repo_fx = Path(__file__).resolve().parent / "fixtures"
    fx = None if args.no_fixtures else (Path(args.fixtures) if args.fixtures else repo_fx)
    res = grade(Path(args.run_dir), args.eval_id, fx if (fx and fx.exists()) else None)
    passed = sum(1 for a in res["assertions"] if a["passed"])
    total = len(res["assertions"])
    for a in res["assertions"]:
        print(f"  {'✓' if a['passed'] else '✗'} {a['text']}  —— {a['evidence']}")
    print(f"  通过 {passed}/{total}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
