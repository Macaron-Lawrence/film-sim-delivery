#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_ccprofiles.py —— 跨平台的创意配置文件安装器（Windows / macOS / Linux 通吃）。

`install-lr-ccprofiles.sh` 是它的 POSIX 包装；没有 bash 的环境（例如 Windows 原生）直接用这个。

用法：
  python3 scripts/install_ccprofiles.py list
  python3 scripts/install_ccprofiles.py install [--src DIR] [--dest DIR] [--dry-run]
  python3 scripts/install_ccprofiles.py remove  [--src DIR] [--dest DIR]

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

import argparse
import os
import shutil
import sys
from pathlib import Path


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


def main() -> int:
    ap = argparse.ArgumentParser(description="安装/卸载 Lightroom 创意配置文件（跨平台）")
    ap.add_argument("action", choices=["list", "install", "remove"])
    ap.add_argument("--src", default=str(default_src()))
    ap.add_argument("--dest", default=str(default_dest()))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src, dest = Path(args.src).expanduser(), Path(args.dest).expanduser()
    files = sorted(src.glob("*.xmp")) if src.is_dir() else []

    print(f"源：  {src}")
    print(f"目标：{dest}")
    print(f"基础配置文件目录（不修改）：{camera_profile_dir(dest)}")
    print(f"找到 {len(files)} 个 .xmp")
    if not files:
        print("\n没有可安装的文件。若还没生成，先跑：")
        print("  python3 scripts/lut-to-ccprofile.py --dir <luts> --space display --protect 0.68")
        return 2

    if args.action == "list" or args.dry_run:
        for f in files:
            print("  ·", f.name)
        if args.dry_run:
            print("\n（--dry-run：未写入任何文件）")
        return 0

    if args.action == "install":
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, dest / f.name)
        print(f"\n✓ 已安装 {len(files)} 个文件")
        print("重启 Lightroom / Bridge 后：配置文件浏览器 → 对应分组；或用同名的 wrapper 预设一键套用。")
        # 提示相机相关依赖
        prof = camera_profile_dir(dest)
        dcps = list(prof.glob("*.dcp")) if prof.is_dir() else []
        print(f"\n提示：创意配置文件需要**相机对应**的基础配置文件才能出现。")
        print(f"     {prof} 下现有 {len(dcps)} 个 .dcp；若缺你机型的，见 references/hosts.md。")
    else:
        removed = 0
        for f in files:
            t = dest / f.name
            if t.exists():
                t.unlink()
                removed += 1
        print(f"\n✓ 已卸载 {removed} 个文件（基础配置文件未动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
