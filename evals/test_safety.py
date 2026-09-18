#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_safety.py —— 安全性回归测试：这些行为坏了，才真的会弄坏用户的文件或让人误报完成。

它测的不是"功能能不能跑"，而是：
  · 默认会不会覆盖原图；
  · 零产物会不会被当成成功；
  · 任意文件名与特殊字符会不会静默失败或生成非法 XML；
  · 安装/卸载会不会覆盖或删掉用户自己的文件；
  · 标定口径不一致会不会被拦住；
  · 文档里会不会引用仓库中不存在的脚本（"幽灵脚本"）。

用法： python3 evals/test_safety.py            # 退出码 0 = 全过
"""
from __future__ import annotations

from pathlib import Path  # noqa: F401  (保持与其他脚本一致的导入顺序)

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
PY = sys.executable

RESULTS = []


def check(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append((name, ok, note))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  —— {note}" if note else ""))


def run(*args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([PY, *[str(a) for a in args]], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", **kw)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def make_lut(path: Path, name: str, n: int = 8) -> None:
    """造一个极小的合成 LUT（求快），形状像胶片：抬暗部 + 肩部封顶。"""
    rows = []
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = [0.05 + 0.80 * (r / (n - 1)) ** 1.2,
                     0.05 + 0.80 * (g / (n - 1)) ** 1.2,
                     0.05 + 0.80 * (b / (n - 1)) ** 1.2]
                rows.append("%.6f %.6f %.6f" % tuple(v))
    path.write_text(f'TITLE "{name}"\nLUT_3D_SIZE {n}\n' + "\n".join(rows) + "\n",
                    encoding="utf-8")


def mk_img(path: Path, size: int = 48) -> None:
    from PIL import Image
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            v = int(255 * x / (size - 1))
            px[x, y] = (v, max(0, v - 12), max(0, v - 24))
    img.save(path)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="filmsim-safety-"))
    luts = work / "luts"
    luts.mkdir()
    # 任意客户风格文件名，其中一个含 XML 特殊字符
    for nm in ["Client Look 01", "Warm & Soft", "Client <Final>", "O'Brien Look"]:
        make_lut(luts / f"{nm}.cube", nm)

    # ── 1. 任意文件名默认处理（不再需要 --allow-unknown）────────────────
    out1 = work / "o1"
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", luts, "--out", out1,
            "--space", "display", "--pre-gain", "1.0")
    made = sorted(out1.glob("*.xmp")) if out1.is_dir() else []
    check("任意文件名默认可处理（4 个全部生成）", r.returncode == 0 and len(made) == 8,
          f"退出码={r.returncode} 产物={len(made)}（期望 8：4 卷 × profile+wrapper）")

    # ── 2. 特殊字符不破坏 XML，表数据完整 ──────────────────────────────
    import importlib.util
    spec = importlib.util.spec_from_file_location("cc", SCRIPTS / "lut-to-ccprofile.py")
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    bad_xml, bad_tbl = [], []
    for f in made:
        try:
            ET.parse(str(f))
        except Exception as exc:  # noqa: BLE001
            bad_xml.append(f"{f.name}: {exc}")
            continue
        s = f.read_text(encoding="utf-8")
        import re
        import zlib
        m = re.search(r'crs:RGBTable="([0-9A-Fa-f]+)"', s)
        if not m:
            continue                      # wrapper 没有表，正常
        tid = m.group(1)
        payload = re.search(r'crs:Table_' + tid + r'="([^"]+)"', s).group(1)
        try:
            cc.decode_table(payload)
            if hashlib.md5(zlib.decompress(cc.b85_decode(payload)[4:])).hexdigest().upper() != tid.upper():
                bad_tbl.append(f"{f.name}: MD5 不匹配")
        except Exception as exc:  # noqa: BLE001
            bad_tbl.append(f"{f.name}: {exc}")
    check("特殊字符（& < ' 空格）不破坏 XML", not bad_xml, f"非法 {len(bad_xml)}：{bad_xml[:2]}")
    check("特殊字符不破坏内嵌表数据", not bad_tbl, f"损坏 {len(bad_tbl)}：{bad_tbl[:2]}")

    # ── 3. 零产物必须是失败 ────────────────────────────────────────────
    empty = work / "empty"
    empty.mkdir()
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", empty, "--out", work / "o2")
    check("空目录 → 非零退出", r.returncode != 0, f"退出码={r.returncode}")
    out3 = work / "o3"
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", luts, "--out", out3, "--only-known")
    n3 = len(list(out3.glob("*.xmp"))) if out3.is_dir() else 0
    check("全部被过滤 → 零产物非零退出且不写文件", r.returncode != 0 and n3 == 0,
          f"退出码={r.returncode} 产物={n3}")

    # ── 4. 直接套图：默认拒绝，原图不被碰 ──────────────────────────────
    mk_img(work / "photo.png")
    before = sha(work / "photo.png")
    lut = luts / "Client Look 01.cube"
    r = run(SCRIPTS / "lr-filmsim.py", "--lut", lut, work / "photo.png")
    check("不给 --out/--in-place → 拒绝运行", r.returncode != 0 and sha(work / "photo.png") == before,
          f"退出码={r.returncode} 原图未变={sha(work / 'photo.png') == before}")

    r = run(SCRIPTS / "lr-filmsim.py", "--lut", lut, "--out", work / "rendered", work / "photo.png")
    ok_out = r.returncode == 0 and (work / "rendered" / "photo_filmsim.png").exists()
    check("--out 写新目录且原图不变", ok_out and sha(work / "photo.png") == before,
          f"退出码={r.returncode} 原图未变={sha(work / 'photo.png') == before}")

    r = run(SCRIPTS / "lr-filmsim.py", "--lut", lut, "--out", work / "rendered", work / "photo.png")
    check("--out 重名输出默认拒绝覆盖", r.returncode != 0, f"退出码={r.returncode}")

    r = run(SCRIPTS / "lr-filmsim.py", "--lut", lut, "--in-place", work / "photo.png")
    baks = list((work / ".filmsim-backups").glob("*.bak")) if (work / ".filmsim-backups").is_dir() else []
    check("--in-place 显式才改，且自动备份", r.returncode == 0 and len(baks) == 1
          and sha(work / "photo.png") != before,
          f"退出码={r.returncode} 备份={len(baks)}")

    # ── 5. 标定口径不一致必须被拒 ──────────────────────────────────────
    cal = work / "cal0.json"
    run(SCRIPTS / "calibrate-luts.py", "--dir", luts, "--mode", "brightness",
        "--protect", "0.0", "--out", cal)
    out4 = work / "o4"
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", luts, "--out", out4,
            "--space", "display", "--calibration", cal, "--protect", "0.68")
    n4 = len(list(out4.glob("*.xmp"))) if out4.is_dir() else 0
    check("标定 protect 与本次不一致 → 拒绝且不生成", r.returncode != 0 and n4 == 0,
          f"退出码={r.returncode} 产物={n4}")

    # ── 6. 安装器：冲突不覆盖、备份、清单、精确回滚 ─────────────────────
    src, dest = work / "psrc", work / "pdest"
    src.mkdir(); dest.mkdir()
    (src / "LookA.xmp").write_text("<x:xmpmeta>A</x:xmpmeta>", encoding="utf-8")
    (src / "LookB.xmp").write_text("<x:xmpmeta>B</x:xmpmeta>", encoding="utf-8")
    (dest / "LookA.xmp").write_text("<x:xmpmeta>用户原有配置</x:xmpmeta>", encoding="utf-8")
    (dest / "UserOwn.xmp").write_text("<x:xmpmeta>与本工具无关</x:xmpmeta>", encoding="utf-8")
    user_hash = sha(dest / "UserOwn.xmp")
    conflict_hash = sha(dest / "LookA.xmp")

    r = run(SCRIPTS / "install_ccprofiles.py", "install", "--src", src, "--dest", dest)
    check("安装遇同名冲突 → 中止且不写任何文件",
          r.returncode != 0 and sha(dest / "LookA.xmp") == conflict_hash
          and not (dest / "LookB.xmp").exists(),
          f"退出码={r.returncode}")

    r = run(SCRIPTS / "install_ccprofiles.py", "install", "--src", src, "--dest", dest, "--force")
    bdir = dest / ".filmsim-backup"
    nbak = len(list(bdir.rglob("*.xmp"))) if bdir.is_dir() else 0
    manifest = dest / ".filmsim-manifest.json"
    check("--force 安装 → 覆盖前备份 + 写清单",
          r.returncode == 0 and nbak == 1 and manifest.is_file(),
          f"退出码={r.returncode} 备份={nbak} 清单={manifest.is_file()}")
    check("用户自己的无关文件未被触碰", sha(dest / "UserOwn.xmp") == user_hash)

    # 被外部改过的文件不删
    (dest / "LookB.xmp").write_text("<x:xmpmeta>用户后来改过</x:xmpmeta>", encoding="utf-8")
    r = run(SCRIPTS / "install_ccprofiles.py", "remove", "--src", src, "--dest", dest)
    check("卸载遇到被改动过的文件 → 中止，不删任何文件",
          r.returncode != 0 and (dest / "LookB.xmp").exists() and (dest / "LookA.xmp").exists(),
          f"退出码={r.returncode}")

    shutil.copy2(src / "LookB.xmp", dest / "LookB.xmp")
    r = run(SCRIPTS / "install_ccprofiles.py", "remove", "--src", src, "--dest", dest)
    check("干净回滚：清单内文件被删，用户的文件保留",
          r.returncode == 0 and not (dest / "LookA.xmp").exists()
          and not (dest / "LookB.xmp").exists() and (dest / "UserOwn.xmp").exists(),
          f"退出码={r.returncode}")

    # ── 7. 嵌套目录：脚本只扫顶层，且这必须是"失败"而不是"成功"───────
    nested = work / "nested"
    (nested / "sub").mkdir(parents=True)
    make_lut(nested / "sub" / "Deep.cube", "Deep")
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", nested, "--out", work / "o5")
    check("嵌套目录里的 LUT 被忽略 → 零产物非零退出（不误报成功）",
          r.returncode != 0, f"退出码={r.returncode}")

    # ── 8. 幽灵脚本：文档里不得引用仓库中不存在的脚本 ──────────────────
    import re
    # 明确由**外部**提供、文档里也标成外部的工具，不算幽灵脚本
    EXTERNAL = {"generate_review.py", "xxx.py"}
    ghosts = []
    for f in list(REPO.rglob("*.md")) + list(REPO.rglob("*.py")):
        if ".git" in f.parts:
            continue
        # CHANGELOG 是历史记录：它必须能写出"删掉了哪些幽灵脚本"，
        # 所以版本日志不参与"文档不得引用不存在脚本"这条检查。
        if f.name == "CHANGELOG.md":
            continue
        for m in re.finditer(r'`(?:scripts/|\./)?([A-Za-z0-9_\-]+\.(?:py|sh))`', f.read_text(encoding="utf-8")):
            nm = m.group(1)
            if nm in EXTERNAL:
                continue
            if not (SCRIPTS / nm).exists() and not (HERE / nm).exists():
                ghosts.append(f"{f.relative_to(REPO)} → {nm}")
    check("文档没有引用不存在的脚本", not ghosts, f"{len(ghosts)} 处：{ghosts[:3]}")

    # ── 9. verify-delivery：坏样本必须 fail、好交付必须 pass ───────────
    vd = SCRIPTS / "verify-delivery.py"
    r = run(vd, "--profile", HERE / "fixtures/bad/portra_noprotect.xmp", "--out", work / "v_bad.json")
    v_bad = json.loads((work / "v_bad.json").read_text(encoding="utf-8")) if (work / "v_bad.json").exists() else {}
    check("无护高光的坏样本 → verdict=fail", r.returncode != 0 and v_bad.get("verdict") == "fail",
          f"verdict={v_bad.get('verdict')}")
    r = run(vd, "--profile", HERE / "fixtures/bad/portra_spacemismatch.xmp", "--out", work / "v_bad2.json")
    check("空间错配的坏样本 → verdict=fail", r.returncode != 0, f"退出码={r.returncode}")

    # 好交付：标定 + 护高光 + 校验
    good_luts = work / "good_luts"
    good_luts.mkdir()
    make_lut(good_luts / "Look.cube", "Look", n=8)
    good_cal = work / "good_cal.json"
    run(SCRIPTS / "calibrate-luts.py", "--dir", good_luts, "--mode", "brightness",
        "--protect", "0.68", "--out", good_cal)
    good_out = work / "good_profiles"
    r = run(SCRIPTS / "lut-to-ccprofile.py", "--dir", good_luts, "--out", good_out,
            "--space", "display", "--calibration", good_cal, "--protect", "0.68")
    prof = next((p for p in sorted(good_out.glob("*.xmp")) if "wrapper" not in p.name), None)
    v_good_path = work / "v_good.json"
    r = run(vd, "--profile", prof, "--lut", good_luts / "Look.cube",
            "--calibration", good_cal, "--out", v_good_path)
    v_good = json.loads(v_good_path.read_text(encoding="utf-8")) if v_good_path.exists() else {}
    check("合格交付 → verdict=pass 且未复算项被显式标出",
          r.returncode == 0 and v_good.get("verdict") == "pass"
          and "brightness_ratio" in v_good.get("unrecomputed", []),
          f"verdict={v_good.get('verdict')} unrecomputed={len(v_good.get('unrecomputed', []))}")
    check("verification.json 不把未复算项当通过",
          all(v_good.get("checks", {}).get(k) is None for k in
              ("brightness_ratio", "top5pct_median", "pct_ge_250", "highlight_detail_std")),
          "未给 --images 时图片级四项应为 null")

    shutil.rmtree(work, ignore_errors=True)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n安全性回归：{passed}/{len(RESULTS)} 通过")
    for name, ok, note in RESULTS:
        if not ok:
            print(f"  ✗ {name}  {note}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
