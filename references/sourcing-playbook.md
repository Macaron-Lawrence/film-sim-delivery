# 开源 LUT 库调研流程（sourcing playbook）

> 什么时候用：用户想要一个**现有库没有**的胶片外观，或想扩库，或怀疑某条来源记录过时。
> 核心原则：**方法与清单可以写进 skill，数据不行**。调研产物落到用户目录，结论回写 `sources.md`。

---

## 八步流程

### 1 定位（找候选）
搜索组合：`<胶片名> lut github`、`film emulation open source`、`<品牌> film simulation dcp/cube`、
社区线索（pixls.us、Reddit r/postprocessing、B 站/知乎的"胶片 LUT 分享"）。
**优先找"有明确许可 + 有方法论"的项目**（按 datasheet 建模 > 手工调色 > 来路不明的转载）。

### 2 许可闸门（不跳）
- 读仓库 `LICENSE`；没有 LICENSE 就看包内 `README.txt`（像 RT 集合那样写在文里）。
- 判定三档：
  - ✅ **可分发**（MIT / CC BY-SA / GPL 等）
  - ⚠️ **仅个人使用**（无许可）→ 可用，但**不写进再分发路径**，在 sources.md 里标出来
  - ❌ **不明且无法核实** → 不用
- 记下署名要求（如 CC BY-SA 需署名 + 相同方式共享），写进 sources.md 那一行。

### 3 可达性（别盲下）
```bash
curl -sIL "<url>" | grep -iE "HTTP/|content-length|content-type"
```
先看大小与类型。400 MB 的包先确认格式与许可，再决定要不要下。

### 4 格式判定（决定能不能进管线）
按 `sources.md` 末尾那张表判断：
- `.cube` / HaldCLUT PNG → ✅ 直接进
- `.clf` → 需降级（注意它工作在线性域）
- `.dcp` → 相机校准，不是风格 LUT
- `.dtstyle` / 参数化预设 → ❌ 转不了，**当场告知用户**，别硬凑

### 5 抽检（3–5 个样本）
```bash
python3 scripts/qa-luts.py --dir <刚下载并转换的目录>
```
看三件事：是否反相（相纸配错）、高光是否被压死、动态范围是否正常。
反相的那几个立刻隔离（`_不适用/`），不要交付。

### 6 标定（逐卷，别共用）
```bash
python3 scripts/calibrate-luts.py --dir <目录> --mode brightness --protect 0.68 \
        --out <目录>/_calibration.json
```
观察 pre-gain 的分布：正常应在 0.4–1.7 之间且**因卷而异**。若一堆卷拿到同一个值，说明标定没生效。

### 7 生成 + 验收
```bash
python3 scripts/lut-to-ccprofile.py --dir <目录> --calibration <目录>/_calibration.json \
        --out <产出目录> --space display --protect 0.68 --label "护高光" --group "<分组名>" \
        --allow-unknown
```
验收判据（缺一不可）：
- 解回误差 ≤ 1/65535
- 元数据 `(1,3,0,0.0,1.0)` 且基底 `Adobe Standard`（走 `--space display` 时的正确配对）
- 画面指标：亮度比 0.95–1.05、最亮 5% ≥240

### 8 记录（回写 sources.md）
每加一个来源就补一条 5 行记录；重核过的来源更新末尾的**核查日期**。
**不要**把文件清单、LUT 数据、许可全文抄进 skill。

---

## 快速判断一个来源值不值得收

| 信号 | 收 | 不收 |
|---|---|---|
| 有许可 + 有方法论说明 | ✅ | |
| 与现有库互补（新卷种 / 新纸种 / 新年代） | ✅ | |
| 只有"调好的图片"没有数据 | | ❌（做不出 LUT） |
| 转载他人 LUT 且无出处 | | ❌ |
| 只有参数化预设（darktable/G'MIC） | | ❌（转不了，除非上游给 HaldCLUT） |
| 覆盖已被更好的来源覆盖 | | ⚠️ 只在更"有味道"时才收 |

## 覆盖现状（避免重复收）

| 类别 | 已有主力来源 |
|---|---|
| 现代彩色负片（Portra/Ektar/Gold…） | spectral_film_lut、spektrafilm、RT 集合 |
| 正片/幻灯片（Velvia/Provia/Kodachrome/Ektachrome） | spectral_film_lut（`print=None`）、RT 集合 |
| 黑白（Tri-X/Double-X/HP5/Delta/APX…） | spectral_film_lut、RT 集合 |
| 电影印片（2383/2393/Technicolor/Eterna） | spectral_film_lut、RT 集合 |
| 红外伪彩（Aerochrome/HIE/IR400） | spectral_film_lut、RT 集合 |
| 富士机内风格（Classic Chrome/Neg/Reala Ace…） | Fuji 创意配置包（无许可，个人用） |
| 宝丽来/一次性相机 | RT 集合（669/690/PX-680/FP-100C/FP-3000b） |

**还没收但有价值的**：Kodak Vision3 200T/50D 的更多印片组合、Agfa 已停产彩负全系、
Ilford 相纸配比、以及各家 faded/expired 变体（RT 集合里有，可按需扩 `curate-rt-halclut.py --all`）。
