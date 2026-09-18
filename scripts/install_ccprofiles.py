#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_ccprofiles.py —— 跨平台的创意配置文件安装器（Windows / macOS / Linux 通吃）。

`install-lr-ccprofiles.sh` 是它的 POSIX 包装；没有 bash 的环境（例如 Windows 原生）直接用这个。

用法：
  python3 scripts/install_ccprofiles.py list    [--src DIR] [--dest DIR]
  python3 scripts/install_ccprofiles.py install [--src DIR] [--dest DIR] [--dry-run] [--force]
  python3 scripts/install_ccprofiles.py remove  [--src DIR] [--dest DIR] [--dry-run] [--force]

安全模型（这是本脚本最重要的部分）：

  1. **永远先打印计划**，说明将要新增 / 覆盖 / 删除哪些文件，然后才动手。
  2. **冲突不静默覆盖**：目标目录里有同名文件且内容不同 → 直接失败退出，除非显式 `--force`。
     建议流程：先 `list` 或 `install --dry-run` 看冲突，确认后再 `install`。
  3. **覆盖前先备份**：被覆盖的旧文件复制到 `<dest>/.filmsim-backup/<时间戳>/`。
  4. **写安装清单**：`<dest>/.filmsim-manifest.json` 记录文件名、sha256、来源与时间。
  5. **卸载按清单精确回滚**：只删清单里记录、且当前 sha256 仍然匹配的文件。
     文件被外部改过、或清单里没有它 → 跳过并报告，绝不动别人的文件（`--force` 才强删）。

目录约定：
  源   ：<root>/lr-ccprofiles（旧布局 <root>/数据/lr-ccprofiles 也认）
  目标 ：按系统自动判定，可用 LR_SETTINGS_DIR 覆盖
         macOS   ~/Library/Application Support/Adobe/CameraRaw/Settings
         Windows %APPDATA%/Adobe/CameraRaw/Settings
         Linux   $XDG_CONFIG_HOME/Adobe/CameraRaw/Settings（默认 ~/.config/…）

注意：基础配置文件（*.dcp，如 "Adobe Standard" / "Adobe Standard Linear"）在**同级**的
CameraProfiles 目录里，本脚本不碰它——那是相机相关的，由用户自行安装（见 references/hosts.md）。
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
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

MANIFEST_NAME = ".filmsim-manifest.json"
BACKUP_DIR_NAME = ".filmsim-backup"
MANIFEST_VERSION = 1


def default_src() -> Path:
    root = Path(os.environ.get("FILMSIM_ROOT", Path.cwd())).expanduser().resolve()
    for cand in (root / "lr-ccprofiles", root / "数据" / "lr-ccprofiles"):
        if cand.is_dir():
            return cand
    return root / "lr-ccprofiles"


def default_dest() -> Path:
    env = os.environ.get("LR_SETTINGS_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Adobe/CameraRaw/Settings"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
        return Path(base) / "Adobe/CameraRaw/Settings"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Adobe/CameraRaw/Settings"


def camera_profile_dir(dest: Path) -> Path:
    return dest.parent / "CameraProfiles"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(dest: Path) -> dict:
    p = dest / MANIFEST_NAME
    if not p.is_file():
        return {"tool": "film-sim-delivery", "version": MANIFEST_VERSION, "entries": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        data = {"tool": "film-sim-delivery", "version": MANIFEST_VERSION, "entries": []}
    data.setdefault("tool", "film-sim-delivery")
    data.setdefault("version", MANIFEST_VERSION)
    return data


def save_manifest(dest: Path, manifest: dict) -> Path:
    p = dest / MANIFEST_NAME
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def plan_install(src: Path, dest: Path, files) -> dict:
    """把每个源文件归类为 新增 / 相同（可跳过）/ 冲突，并给出冲突详情。"""
    add, same, conflict = [], [], []
    for f in files:
        t = dest / f.name
        if not t.exists():
            add.append(f)
            continue
        if sha256_of(t) == sha256_of(f):
            same.append(f)
        else:
            conflict.append((f, t, t.stat().st_size))
    return {"add": add, "same": same, "conflict": conflict}


def main() -> int:
    ap = argparse.ArgumentParser(description="安装/卸载 Lightroom 创意配置文件（跨平台，带备份与清单）")
    ap.add_argument("action", choices=["list", "install", "remove"])
    ap.add_argument("--src", default=str(default_src()))
    ap.add_argument("--dest", default=str(default_dest()))
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写任何文件")
    ap.add_argument("--force", action="store_true",
                    help="覆盖同名冲突文件（install）/ 强删清单里没有或已被改动的文件（remove）")
    ap.add_argument("--no-backup", action="store_true", help="覆盖时不备份（不推荐）")
    args = ap.parse_args()

    src, dest = Path(args.src).expanduser(), Path(args.dest).expanduser()
    files = sorted(src.glob("*.xmp")) if src.is_dir() else []
    manifest = load_manifest(dest)
    known = {e.get("name") for e in manifest["entries"]}

    print(f"源：  {src}")
    print(f"目标：{dest}")
    print(f"基础配置文件目录（不修改）：{camera_profile_dir(dest)}")
    print(f"清单：{dest / MANIFEST_NAME}"
          f"{'' if known else '（还没有；说明本工具未在此目录安装过东西）'}")
    print(f"找到 {len(files)} 个 .xmp")
    if not files and args.action != "remove":
        print("\n没有可安装的文件。若还没生成，先跑：")
        print("  python3 scripts/lut-to-ccprofile.py --dir <luts> --space display --protect 0.68")
        return 2

    # ── list：只列源目录内容 ────────────────────────────────────────────
    if args.action == "list":
        for f in files:
            tag = "已在目标且内容相同" if (dest / f.name).exists() and sha256_of(dest / f.name) == sha256_of(f) \
                else ("目标已有同名但内容不同 = 冲突" if (dest / f.name).exists() else "新增")
            print(f"  · {f.name}   [{tag}]")
        return 0

    # ── install ────────────────────────────────────────────────────────
    if args.action == "install":
        pl = plan_install(src, dest, files)
        print(f"\n计划：新增 {len(pl['add'])}，已相同可跳过 {len(pl['same'])}，冲突 {len(pl['conflict'])}")
        for f in pl["add"]:
            print(f"  + {f.name}")
        for f in pl["same"]:
            print(f"  = {f.name}（内容相同，跳过）")
        for f, t, size in pl["conflict"]:
            print(f"  ! {f.name} —— 目标已存在且内容不同（目标 {size} 字节）。"
                  f"覆盖会先备份到 {dest / BACKUP_DIR_NAME}/")

        if pl["conflict"] and not args.force:
            print(f"\n✗ 有 {len(pl['conflict'])} 个冲突，已中止，**未写入任何文件**。\n"
                  f"  先确认这些同名文件是不是你原有/别人的配置：\n"
                  f"    {dest}\n"
                  f"  确认可以覆盖再重跑并加 --force（会自动备份）。", file=sys.stderr)
            return 1

        if args.dry_run:
            print("\n（--dry-run：未写入任何文件）")
            return 0

        backups = {}
        if pl["conflict"] and not args.no_backup:
            bdir = dest / BACKUP_DIR_NAME / time.strftime("%Y%m%d-%H%M%S")
            bdir.mkdir(parents=True, exist_ok=True)
            for f, t, _ in pl["conflict"]:
                shutil.copy2(t, bdir / t.name)
                backups[f.name] = str(bdir / t.name)
            print(f"\n已备份 {len(backups)} 个被覆盖的文件 → {bdir}")

        dest.mkdir(parents=True, exist_ok=True)
        entries = {e["name"]: e for e in manifest["entries"] if e.get("name")}
        for f in pl["add"] + [c[0] for c in pl["conflict"]] + pl["same"]:
            target = dest / f.name
            if f not in pl["same"]:
                shutil.copy2(f, target)
            entries[f.name] = {
                "name": f.name,
                "sha256": sha256_of(target),
                "source": str(f),
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "backup": backups.get(f.name),
            }
        manifest["entries"] = sorted(entries.values(), key=lambda e: e["name"])
        mpath = save_manifest(dest, manifest)
        print(f"✓ 已安装 {len(pl['add']) + len(pl['conflict'])} 个文件"
              f"（跳过 {len(pl['same'])} 个内容相同的）")
        print(f"清单已更新：{mpath}")
        print("重启 Lightroom / Bridge 后：配置文件浏览器 → 对应分组；或用同名的 wrapper 预设一键套用。")

        prof = camera_profile_dir(dest)
        dcps = list(prof.glob("*.dcp")) if prof.is_dir() else []
        print(f"\n提示：创意配置文件需要**相机对应**的基础配置文件才能出现。")
        print(f"     {prof} 下现有 {len(dcps)} 个 .dcp；若缺你机型的，见 references/hosts.md。")
        print("     本脚本只能证明文件已就位，**不能证明 Lightroom 真的接受了它**——请在宿主里实测。")
        return 0

    # ── remove：按清单精确回滚 ─────────────────────────────────────────
    entries = {e["name"]: e for e in manifest["entries"] if e.get("name")}
    if not entries:
        print("\n清单里没有任何本工具安装过的记录。")
        if args.force:
            print("  --force：退化为「按源目录同名删除」，风险自负。")
            targets = [(f.name, None) for f in files]
        else:
            print("  不做任何删除。若确实要按源目录同名强删，加 --force。")
            return 1
    else:
        targets = [(n, e) for n, e in sorted(entries.items())]

    print(f"\n计划：从清单回滚 {len(targets)} 个文件")
    to_delete, skipped = [], []
    for name, e in targets:
        t = dest / name
        if not t.exists():
            skipped.append((name, "目标不存在"))
            continue
        cur = sha256_of(t)
        if e is None:
            to_delete.append((name, None, cur))
        elif cur == e.get("sha256"):
            to_delete.append((name, e, cur))
        else:
            skipped.append((name, f"已被改动（清单 {str(e.get('sha256'))[:12]}… / 现在 {cur[:12]}…）"))

    for name, e, cur in to_delete:
        print(f"  - {name}")
    for name, why in skipped:
        print(f"  ~ 跳过 {name}：{why}")

    if skipped and not args.force:
        print(f"\n✗ 有 {len(skipped)} 个文件无法确认是本次安装的产物，已中止，**未删除任何文件**。\n"
              f"  这些可能是你自己改过的配置。确认要删再加 --force。", file=sys.stderr)
        return 1

    if skipped and args.force:
        # --force = 明知无法确认来源也要删。逐个喊出来，别让删除悄悄发生。
        for name, why in skipped:
            print(f"  ! --force：仍然删除 {name}（{why}）", file=sys.stderr)
            to_delete.append((name, None, None))
        skipped = []

    if args.dry_run:
        print("\n（--dry-run：未删除任何文件）")
        return 0

    removed = 0
    for name, e, cur in to_delete:
        (dest / name).unlink()
        entries.pop(name, None)
        removed += 1
    manifest["entries"] = sorted(entries.values(), key=lambda e: e["name"])
    save_manifest(dest, manifest)
    print(f"\n✓ 已回滚 {removed} 个文件（清单同步更新；基础配置文件未动）")
    if skipped and args.force:
        print(f"  注意：--force 下忽略了 {len(skipped)} 个未经确认的文件，它们仍在目标目录里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
