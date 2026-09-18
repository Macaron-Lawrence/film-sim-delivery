#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_grader.py —— 让评分器本身在 CI 里被跑一遍：造一个"正确交付"的候选目录，要求满分。

为什么需要它：评分器是评测的裁判，如果它自己坏了（断言写太严、字段读不到、复算逻辑崩），
评测结论就是错的。这个测试固定一个已知正确的交付，断言 grade.py 给出满分，
并断言它确实**自己复算**了 decode_error_lsb（而不是读交付方填的数字）。

用法： python3 evals/test_grader.py        # 退出码 0 = 通过
"""
from __future__ import annotations

from pathlib import Path  # noqa: F401

import json
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
FIXTURES = HERE / "fixtures"
PY = sys.executable


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *[str(a) for a in args]], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    if not (FIXTURES / "luts/portra_like.cube").exists():
        print("缺 fixture：先跑 evals/make_fixtures.py")
        return 1

    work = Path(tempfile.mkdtemp(prefix="filmsim-grader-"))
    luts = work / "luts"
    luts.mkdir()
    shutil.copy2(FIXTURES / "luts/portra_like.cube", luts / "portra_like.cube")

    fails = []

    # ① 造一个"正确交付"：逐卷标定 + 护高光 + 生成 + 真算验收凭证
    cal = luts / "cal.json"
    r = run(SCRIPTS / "calibrate-luts.py", "--dir", luts, "--mode", "brightness",
            "--protect", "0.68", "--out", cal)
    if r.returncode != 0:
        print("✗ 标定失败：", r.stdout[-400:], r.stderr[-400:])
        return 1

    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", luts, "--out", work,
            "--space", "display", "--calibration", cal, "--protect", "0.68", "--label", "HP")
    prof = next((p for p in sorted(work.glob("*.xmp")) if "wrapper" not in p.name), None)
    if r.returncode != 0 or prof is None:
        print("✗ 生成失败：", r.stdout[-400:], r.stderr[-400:])
        return 1

    (work / "diagnosis.json").write_text(json.dumps({
        "root_cause_code": "missing_highlight_protection",
        "summary": "空间与基底配对正确，但表格未做护高光，胶片肩部把纯白封顶。",
        "evidence": {"white_before": 216.8, "white_after": 255.0, "mid_after": 125.0},
    }, ensure_ascii=False), encoding="utf-8")

    r = run(SCRIPTS / "verify-delivery.py", "--profile", prof, "--lut", luts / "portra_like.cube",
            "--calibration", cal, "--out", work / "verification.json")
    if r.returncode != 0:
        print("✗ verify-delivery 未通过：", r.stdout[-600:], r.stderr[-300:])
        fails.append("verify-delivery 在合格交付上没给出 pass")

    # ② 评分器应当满分，并且自己复算了 decode_error_lsb
    r = run(HERE / "grade.py", work, "--eval", 2)
    out = r.stdout + r.stderr
    print(out[-1400:])
    if r.returncode != 0:
        fails.append(f"评分器在已知正确的交付上没给满分（退出码 {r.returncode}）")
    if "独立复算 decode_error_lsb" not in out:
        fails.append("评分器没有出现 decode_error_lsb 的独立复算断言")
    elif "✓ 独立复算 decode_error_lsb" not in out:
        fails.append("评分器的 decode_error_lsb 独立复算未通过")
    if "图片级指标" not in out:
        fails.append("评分器没有对图片级指标声明做出处理")

    # ③ 反例：把交付文件删掉，评分器必须不是满分（防止"永远绿"）
    shutil.rmtree(work / "luts")
    for p in work.glob("*.xmp"):
        p.unlink()
    r = run(HERE / "grade.py", work, "--eval", 2)
    if r.returncode == 0:
        fails.append("删掉产物后评分器仍然满分——评分器没有真的在检查产物")

    shutil.rmtree(work, ignore_errors=True)
    if fails:
        print("\n评分器自检失败：")
        for f in fails:
            print("  ✗", f)
        return 1
    print("\n评分器自检：✅ 通过（正确交付满分、产物缺失不再满分、独立复算生效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
