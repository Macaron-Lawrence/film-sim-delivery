---
name: film-sim-delivery
description: 把胶片模拟外观（.cube LUT / HaldCLUT PNG / 光谱模拟烘出来的卷 / 开源 LUT 库里的风格）交付到真实摄影工作流里——Lightroom Classic / Adobe Camera Raw 的「创意配置文件（creative profile）」、ART 的 CLUT 与加工配置、或直接批处理图片。Use this skill whenever the user mentions 胶片模拟、胶片色、film simulation、LUT、预设、配色文件、creative profile、Portra/Velvia/Kodachrome/Tri-X/HP5 等胶片卷名，或者抱怨「套上胶片预设后发灰/偏暗/高光被压平/颜色不对」，或者想把一批 LUT 装进 Lightroom/ART、想从开源 LUT 库里挑素材、想自己烘某个胶片卷——即使他们没有说「skill」或「LUT」这些词。不适用于：相机自带配置文件缺失/相机匹配（那是 .dcp 相机校准问题）、视频调色与视频 LUT、以及纯通用后期（加颗粒暗角、抠图、格式转换）。
---

# 胶片模拟交付（film-sim delivery）

把「一个胶片外观」变成「装进用户真正在用的软件里、且亮度/高光正确」的成品。
本 skill 只负责**交付层**：拿到 LUT → 标定 → 转目标格式 → 安装 → 验收。
素材（LUT 本体、成品配置）**不进 skill 目录**，放在 `FILMSIM_ROOT` 指向的目录里。

## 0. 三条硬规则（先读，能省掉 80% 的返工）

1. **Lightroom 不支持 .cube / HaldCLUT**。要进 LR，必须做成 **Adobe 创意配置文件（XMP + 内嵌 RGBTable）**。
   直接给用户 `.cube` 或让他"导入 LUT"是错的——LR 没有这个入口。
   （退路：如果用户的环境拿不到 dcp、或只要"能叠加的预设"，用 `lut-to-xmp.py`，
   那是曲线近似，保真度降到 ~80%，要明确告诉用户。）
2. **每个 LUT 的曝光定位都不同，必须逐卷标定**。实测跨度 0.40–1.67；
   共用一个系数会让某些卷明显偏亮或偏暗。`calibrate-luts.py` 用二分求根算出来。
3. **不做护高光，纯白会被压到 ~209**（胶片印片肩部），高光区细节只剩原来的 1/6——
   用户会直接说"高光被切掉了"。默认就带 `--protect 0.68`。

细节都在 `references/pitfalls.md`（7 条，全是踩出来的）。

## 1. 决策树：用户要什么 → 走哪条路

```
用户想干什么？
├─ 「把这个 LUT 装进 Lightroom」 ────────────→ §2 主线（calibrate → ccprofile → install）
├─ 「套上后发灰/偏暗/高光被压平」 ──────────→ §4 诊断修复（多半缺护高光或标定）
├─ 「批量给一批图套胶片」 ─────────────────→ §3-A（apply-look.sh / try-looks.py）
├─ 「在 ART 里用」 ───────────────────────→ §3-B（make-art-profiles / setup-art-bridge）
├─ 「我要某个胶片（Portra/Velvia/黑白…）」 ─→ §5 取素材（sources.md + fetch-sources）
└─ 「只能用预设，不能装配置文件」 ─────────→ §3-C（曲线近似，说明保真度）
```

## 2. 主线：LUT → Lightroom 创意配置文件

```bash
# 0) 环境（一次性）：Python 3.9+，装依赖
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FILMSIM_ROOT=/path/to/your/library      # 素材与产物都放这里

# 1) 体检：反相 / 高光压死 / 相纸配错的 LUT 先挑出来
python3 scripts/qa-luts.py --dir "$FILMSIM_ROOT/luts"

# 2) 标定曝光定位（逐卷算 pre-gain；护高光阈值一起算进去）
python3 scripts/calibrate-luts.py --dir "$FILMSIM_ROOT/luts" \
        --mode brightness --protect 0.68 --out "$FILMSIM_ROOT/luts/_calibration.json"

# 3) 生成 Adobe 创意配置文件 + wrapper 预设
python3 scripts/lut-to-ccprofile.py --dir "$FILMSIM_ROOT/luts" \
        --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
        --out "$FILMSIM_ROOT/lr-ccprofiles" \
        --space display --protect 0.68 --label "护高光" --group "胶片模拟"

# 4) 装进 Adobe
FILMSIM_ROOT="$FILMSIM_ROOT" bash scripts/install-lr-ccprofiles.sh
```

**为什么是 `--space display`**：这个参数决定表格接收/输出的是显示域还是线性域的数据，
必须和**基底配置文件**配对——`display` → 基底 `Adobe Standard`（元数据 `(1,3,0,0.0,1.0)`），
`linear` → 基底 `Adobe Standard Linear`（元数据 `(3,1,0,1.0,1.0)`）。
配错的典型症状就是"整张发灰"。详见 `references/rgb-table-format.md` §3。

装完告诉用户：重启 Lightroom / ACR → 配置文件浏览器里找对应分组。别忘了他还需要相机对应的 `*.dcp`
（没有的话 profile 不会出现）。

## 3. 支线

**A. 直接套图（不进 LR）**
```bash
python3 scripts/lr-filmsim.py --lut "$FILMSIM_ROOT/luts/xxx.cube" --pre-gain 0.3472 photo.tif
bash scripts/apply-look.sh xxx --out 成品 照片目录/        # 简写匹配 LUT 名
python3 scripts/try-looks.py 照片.tif --lut-dir "$FILMSIM_ROOT/luts"   # 批量试版 + 对比图
```
`lr-filmsim.py` 也吃 HaldCLUT PNG（自动识别 level，超大网格自动降采样）。

**B. ART（Another RawTherapee）**
- 静态外观：HaldCLUT PNG（`cube-to-hald.py` 从 .cube 转）
- 实时物理参数：spektrafilm 桥接（`setup-art-bridge.sh`）
- ⚠️ ART 的 external-3dLUT 在 JSON 里的 `command` **必须是纯 ASCII 路径**，中文路径会报
  `Invalid LUT parameters`——这是最容易踩的坑之一。
- ART 的 CLUT 目录从 Preferences 里设；`.arp` 加工配置用 `make-art-profiles.py` 生成。

**C. 只能给预设（保真度降级）**
```bash
python3 scripts/lut-to-xmp.py --dir "$FILMSIM_ROOT/luts" --out "$FILMSIM_ROOT/lr-presets"
```
从 LUT 反解出曲线 + 8 带 HSL + 颜色分级写成 XMP 预设。**必须告知用户这是近似**（实测约 75–85%），
因为 3D LUT 的跨通道色相扭转 LR 表达不了。

## 4. 诊断：套上后不对，怎么查

按这个顺序，每一步都能量化：

| 症状 | 先查 | 量化判据（相对原图） |
|---|---|---|
| 整张发灰、对比低 | 元数据与基底是否配对（§2 注释） | 中灰应在 128 附近；错配时整片漂移 |
| 偏暗 | pre-gain 是否逐卷标定过 | 平均亮度比应在 0.95–1.05 |
| 高光发白/没细节 | 有没有做护高光 | 最亮 5% 应 ≥240；未护高光只有 ~209 |
| 颜色整个反了 | 相纸配错（正片配了负片相纸） | `qa-luts.py` 会直接标红 |
| 某些卷偏、某些卷正常 | 共用了同一个 pre-gain | 逐卷标定后应一致 |

```bash
# 一眼看到底：灰阶响应 + 画面指标
python3 scripts/qa-luts.py --dir "$FILMSIM_ROOT/luts"
```

## 5. 取素材（允许基于开源 LUT 库做调查）

**先读 `references/sources.md`**（10 个来源 × 5 行：许可 / 格式 / 覆盖 / 取用命令 / 核查日期）。
需要新来源时按 `references/sourcing-playbook.md` 的 8 步走——**许可闸门**和**抽检**两步不能跳。

```bash
bash scripts/fetch_sources.sh              # 列出可拉取的来源
bash scripts/fetch_sources.sh rt           # RawTherapee 295 个 HaldCLUT（402MB, CC BY-SA 4.0）
bash scripts/fetch_sources.sh spectra      # spectral_film_lut（MIT）现烘卷，含黑白/正片/电影印片
python3 scripts/curate-rt-halclut.py --src "$FILMSIM_ROOT/sources/HaldCLUT"   # 挑经典卷
python3 scripts/bake-spectral-luts.py --list                                  # 看 87 个可用卷名
```

**边界**：可以下载、转换、派生、回写来源表；**不要**把 LUT 数据、完整文件枚举、许可全文打包进 skill；
不要用无许可证的库（abpy、ComfyUI-Darkroom）做再分发来源。

## 6. 验收（每次交付都要做，并且要留下机器可读的凭证）

```bash
bash scripts/selftest.sh        # 造 LUT → 标定 → 转配置 → 解回比对 + 护高光断言
```

自检通过后，对真实交付再做一次，并**把结果写成 `verification.json`**（放在交付目录里）。
之所以要写成文件而不是只在对话里汇报：验收结论必须可被独立复核，别人（或未来的你）
不应采信自述。格式见 `references/verification-schema.md`，最少要包含：

| 字段 | 含义 |
|---|---|
| `params.space` / `params.base_profile` / `params.metadata` | 表格空间、基底配置文件、元数据三元组（必须配对） |
| `params.pre_gain` / `params.protect` | 该卷的标定值与护高光阈值 |
| `checks.decode_error_lsb` | 交付表解回后与源 LUT 的最大误差（≤1.0） |
| `checks.gray_response` | 灰阶 0/32/64/96/128/160/192/224/255 的输出值 |
| `checks.mid_gray_out` / `checks.white_out` | 中灰与纯白输出（白 ≥250） |
| `checks.brightness_ratio` | 相对原图的平均亮度比（0.95–1.05） |
| `checks.top5pct_median` / `checks.pct_ge_250` / `checks.highlight_detail_std` | 高光三项 |
| `outputs.profile` / `outputs.wrapper` / `outputs.table_id` | 产物路径与表 ID（ID 应为表的 MD5） |

## 7. 目录与脚本索引

```
scripts/
├── lut-to-ccprofile.py     ★ 主线：LUT → Adobe RGBTable（XMP + wrapper）
├── calibrate-luts.py       ★ 逐卷标定 pre-gain（midgray / brightness × protect）
├── install-lr-ccprofiles.sh★ 安装/卸载（跨平台路径 + LR_SETTINGS_DIR 覆盖）
├── qa-luts.py              ★ 体检：反相/压死/错配
├── lr-filmsim.py             套图核心（.cube + HaldCLUT，pre-gain/护高光）
├── apply-look.sh             按简写名套图，支持整目录
├── try-looks.py              批量试版 + 拼对比图
├── cube-to-hald.py           .cube → HaldCLUT PNG（给 ART / RawTherapee）
├── lut-to-xmp.py             退路：反解成 LR 预设（近似）
├── bake-spectral-luts.py     用 spectral_film_lut 烘卷（MIT）
├── curate-rt-halclut.py      从 RT 集合挑卷
├── fetch_sources.sh          拉上游素材（含许可提示）
└── selftest.sh               最小闭环自检
```

references/：`sources.md`（来源表）· `sourcing-playbook.md`（调研流程）·
`rgb-table-format.md`（二进制格式规范）· `pitfalls.md`（7 条硬坑）· `calibration.md`（标定与护高光原理）·
`hosts.md`（宿主/系统/相机适配矩阵）· `verification-schema.md`（交付凭证格式）

## 8. 跨平台说明

- 依赖：Python 3.9+ + numpy / Pillow / tifffile。macOS / Windows / Linux 都可用。
- Adobe 配置目录自动探测：macOS `~/Library/Application Support/Adobe/CameraRaw/Settings`、
  Windows `%APPDATA%\Adobe\CameraRaw\Settings`、Linux `~/.config/Adobe/CameraRaw/Settings`；
  可用 `LR_SETTINGS_DIR` 覆盖。
- `scripts/make-lr-external-editor-app.sh`（在项目里，不随 skill）是 **macOS 专用**；
  Windows 用 `.bat` 包装同一条命令即可。
- 本 skill 只依赖标准 CLI + Python，不依赖任何特定 agent 平台的私有工具。

## 9. 适配范围（宿主 / 系统 / 相机）

**核心能力是宿主无关、系统无关、相机无关的**；有依赖的只有两处，都写在 `references/hosts.md`：

| 维度 | 覆盖情况 |
|---|---|
| **修图宿主** | Lightroom Classic / ACR（创意配置文件）、Photoshop（`.cube` 颜色查找）、ART / RawTherapee（HaldCLUT）、GIMP 系（HaldCLUT）、视频与 AI 出图管线（直接给 `.cube` 或用 `lr-filmsim.py` 批处理）；**未验证**：Capture One / Affinity / darktable `lut3d`（清单见 hosts.md §5） |
| **操作系统** | macOS / Windows / Linux 全通；Adobe 目录自动判定 + `LR_SETTINGS_DIR` 覆盖；原生 Windows 用 `.py` 入口（`.sh` 只是 POSIX 包装） |
| **相机** | 脚本里**没有任何机型或安装路径假设**，profile 的 `crs:CameraModelRestriction` 留空 → 不绑定机型。唯一依赖：基础配置文件 `Adobe Standard`（display 族）或 `Adobe Standard Linear`（linear 族）要存在于本机 `CameraProfiles/` |
| **AI / agent 宿主** | 标准 Agent Skills 格式，复制文件夹即可用于 Claude Code / Codex / Cursor 等；**不依赖任何宿主专有 API** |
| **语言** | 正文中文；完整英文说明见仓库根目录 `README.md`（中文版 `README.zh.md`），二者与源码不一致时以源码为准 |

取素材与许可见 `references/sources.md`（本 skill 不打包任何 LUT 数据）；调研新来源的流程见
`references/sourcing-playbook.md`。
