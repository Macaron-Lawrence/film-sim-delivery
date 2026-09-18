# 宿主 / 系统 / 相机 适配矩阵

> 结论先讲：**核心能力（LUT → 创意配置文件 / 套图 / 标定 / 护高光）是宿主无关、系统无关、相机无关的**。
> 真正有依赖的只有两处：**目标宿主认哪种产物**，以及**创意配置文件需要相机对应的基础配置文件**。

---

## 1. 修图宿主：谁能吃哪种产物

| 宿主 | 创意配置文件 XMP（内嵌 RGBTable） | `.cube` | HaldCLUT PNG | 预设 XMP | 本 skill 的路径 |
|---|---|---|---|---|---|
| **Lightroom Classic / ACR**（macOS+Win） | ✅ 原生 | ❌ | ❌ | ✅ | `lut-to-ccprofile.py`（主）/ `lut-to-xmp.py`（退路） |
| **Photoshop** | ✅（走 Camera Raw 引擎） | ✅ 颜色查找图层 | ✅ 部分 | — | 直接把 `.cube` 交给 PS；或先做配置文件 |
| **Bridge** | ✅ | ❌ | ❌ | ✅ | 同 ACR |
| **ART / RawTherapee** | ❌ | ❌（Film Simulation 只认 HaldCLUT） | ✅ | `.arp` 加工配置 | `cube-to-hald.py`；ART 另有 external-3dLUT（JSON/CLF） |
| **darktable** | ❌ | ⚠️ 较新版本有 `lut3d` 模块（读 .cube/HaldCLUT），需实测 | ⚠️ 同上 | `.dtstyle`（参数化，**不可由 LUT 生成**） | 用 `.cube` 走 `lut3d`，或另走 darktable 自己的预设体系 |
| **GIMP / Krita / digiKam** | ❌ | ⚠️ 视插件 | ✅ G'MIC / CLUT 插件 | — | 用 `cube-to-hald.py` 出 HaldCLUT |
| **Capture One / Affinity / Pixelmator** | ❌ | ⚠️ **未验证** | ⚠️ 未验证 | 自家 Styles 格式 | 未覆盖（见 §5） |
| **DaVinci Resolve 等视频宿主** | ❌ | ✅ 原生 | — | — | 本 skill 面向图片；`.cube` 可直接给 Resolve |
| **ComfyUI / AI 出图管线** | ❌ | ⚠️ 需第三方 LUT 节点 | ⚠️ 同上 | — | 用 `lr-filmsim.py` 对出图结果批处理（最稳），或把 `.cube` 交给有 LUT 节点的插件 |
| **本 skill 的命令行** | — | ✅ | ✅ | — | `lr-filmsim.py` / `apply-look.sh` |

一句话选路：**Lightroom 系 → 创意配置文件；ART/RT → HaldCLUT；PS/Resolve/AI 管线 → 直接用 `.cube`。**

---

## 2. 相机：唯一的硬依赖是"基础配置文件"

创意配置文件（`crs:PresetType="Look"`）必须**挂在某个基础配置文件上**才能出现在 LR/ACR 的浏览器里。
我们生成时用的是：

| 族 | `params.base_profile` | 何时可用 |
|---|---|---|
| `--space display`（推荐） | `Adobe Standard` | LR/ACR 对**支持的相机**内置；绝大多数现代机型都有 |
| `--space linear` | `Adobe Standard Linear` | 需要额外安装 `.dcp`（公开的 Fujifilm 创意配置包内含 1464 个机型，`fetch_sources.sh fuji` 可取） |

**自检清单**（装完配置文件后若"浏览器里看不到"）：

1. 确认 `CameraProfiles` 目录里有没有你机型的 dcp：
   - macOS `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/`
   - Windows `%APPDATA%\Adobe\CameraRaw\CameraProfiles\`
   - Linux `~/.config/Adobe/CameraRaw/CameraProfiles/`
   - 搜 `*<机型>*Adobe Standard*.dcp`
2. 没有 → 三条路：
   a. 装线性基底 dcp（`fetch_sources.sh fuji`），改生成 `--space linear`；
   b. 退回**预设**路径（`lut-to-xmp.py`，不需要 dcp，代价是保真度降到约 80%）；
   c. 打开的是 RAW 吗？创意配置文件对**非 RAW**（JPEG/TIFF）通常不生效。
3. 我们的 profile 里 `crs:CameraModelRestriction` **留空** → 不限制机型，任何相机都能用同一份配置文件。

**相机完全无关的部分**：LUT/表格本身、标定（pre-gain）、护高光、命令行套图、ART 的 CLUT。
换句话说：**相机只影响"配置文件能不能出现在 LR 里"，不影响外观的正确性。**

---

## 3. 系统：三平台都可用

| 项 | macOS | Windows | Linux |
|---|---|---|---|
| Adobe 目录自动判定 | ✅ | ✅（`%APPDATA%`） | ✅（`XDG_CONFIG_HOME`），可用 `LR_SETTINGS_DIR` 覆盖 |
| Python 脚本 | ✅ | ✅ | ✅ |
| `.sh` 便捷包装 | ✅ | ⚠️ 需 Git Bash / WSL | ✅ |
| **原生 Windows（无 bash）** | — | 用 **Python 入口**：`python scripts\selftest.py`、`python scripts\install_ccprofiles.py install` | — |

- 依赖：Python **3.9+** + `numpy` / `Pillow` / `tifffile`（`pip install -r requirements.txt`）。
- 文件读写按 UTF-8；中文路径/文件名可用。**例外**：给 ART 的 external-3dLUT 里 `command`
  必须是纯 ASCII 路径（见 `pitfalls.md` 第 5 条）。
- 需要 Photoshop 的 `.cube`、ART 的 HaldCLUT 时不需要额外系统依赖——都由 Python 脚本产出。

---

## 4. AI（agent）宿主

- 格式：标准 **Agent Skills**（`SKILL.md` + `scripts/` + `references/` + `assets/`），
  Claude Code / Codex / Cursor / DSH 等兼容客户端**复制文件夹即可用**。
- **不依赖任何宿主专有 API**：没有 subagent / goal / 记忆库调用；全部能力都能落到
  "跑一条 shell 命令 + 读写文件"。
- 宿主支持并行子代理时，可以用于评测扇出（可选，非必需）。
- 建议的调用方式：让 agent 直接执行 `python3 scripts/*.py …`，把结果读回来判断——
  脚本都支持命令行参数与明确的退出码。

---

## 5. 明确未覆盖 / 需实测的情况（诚实清单）

| 情况 | 状态 | 建议 |
|---|---|---|
| Capture One / Affinity Photo / Pixelmator | **未验证** | 若它们能读 `.cube`，直接用我们的 `.cube`；否则走预设体系 |
| darktable `lut3d` 模块 | **未实测** | 先用一个 `.cube` 在本地试，能读就把 pipeline 的 `.cube` 直接给它 |
| 视频宿主 / 视频 LUT | **不在范围** | 本 skill 只处理静态图片；`.cube` 本身是通用的 |
| Lightroom **Mobile / 云端版** | **不支持** | 移动端不支持自定义创意配置文件 |
| 相机不在 Adobe 支持列表 | 受限 | 见 §2 的三条路；或改用 ART/RawTherapee 直出（他们自己能解 RAW） |
| 非 RAW（JPEG/TIFF）走创意配置文件 | 通常不生效 | 改用 `lr-filmsim.py` / `apply-look.sh` 直接处理图片 |
| 相机 **型号/位置** 相关路径 | 无硬编码 | 脚本里没有任何机型或安装路径假设，机型只通过 dcp 文件名体现 |
