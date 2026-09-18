# 开源胶片模拟 LUT 来源表

> 每条 5 行固定格式，便于"发现过时就直接改这一行"。
> **核查日期**记在每条末尾；超过半年没核过的，用 `references/sourcing-playbook.md` 的流程重核一遍。
> 本表只写"去哪拿 + 怎么拿 + 能不能用"，**不收录 LUT 数据本身**。

---

### RawTherapee Film Simulation Collection
- 许可：CC BY-SA 4.0（包内 `README.txt`）｜署名 Pat David / Pavlov Dmitry / Michael Ezra
- 格式：HaldCLUT PNG（level 12 为主，个别 level 16）｜295 个｜含 `+ ++ +++ - -- ---` 推拉冲洗变体
- 取用：`bash scripts/fetch_sources.sh rt`（`http://rawtherapee.com/shared/HaldCLUT.zip`，402 MB，实测 HTTP 200）
- 适配：✅ 直接进交付层：`curate-rt-halclut.py --src …` → 标定 → `lut-to-ccprofile.py`
- 核查：2026-09-18

### JanLohse/spectral_film_lut
- 许可：**MIT**（最干净）
- 格式：Python GUI 导出 LUT（`.cube`）｜87 个卷：30 负片 / 10 正片 / 18 印片 / 4 黑白 / 5 反转型相纸｜另有颗粒叠加导出
- 取用：`bash scripts/fetch_sources.sh spectra`（pip，需 Python ≥3.11）
- 适配：✅ 现烘补缺口（黑白、正片、Aerochrome 红外伪彩、Instax、Vision3×2383）
- 核查：2026-09-18

### andreavolpato/spektrafilm（原 agx-emulsion）
- 许可：代码 **GPLv3**；剖面与 LUT **CC BY-SA 4.0** + 自定义条款（可商用、禁转售）
- 格式：Python（Qt GUI）+ `spektrafilm-lut` CLI｜20 个彩色卷 + 8 种相纸｜**无黑白**，正片需相纸 None（CLI 做不了）
- 取用：`bash scripts/fetch_sources.sh spektra`（uv 安装，需 Python 3.13）
- 适配：✅ 光谱物理模拟；烘出 .cube 后走交付层；也能与 ART 实时联动
- 核查：2026-09-18

### TingfengLuo/Camera-Profile-for-Fujifilm-Film-Simulation
- 许可：**仓库未声明**（⚠️ 仅个人使用，不作为再分发来源）
- 格式：创意配置文件 `.xmp`（内嵌 RGBTable）+ 1464 个「Adobe Standard Linear」基础 `.dcp`
- 取用：`bash scripts/fetch_sources.sh fuji`
- 适配：✅ 11 款 Fuji 风格（Provia/Velvia/Astia/Classic Chrome/Classic Neg/Nostalgic Neg/Eterna/Pro Neg Std+Hi/Reala Ace/Bleach Bypass）+ 线性基底 dcp
- 核查：2026-09-18

### Adobe 自带 Film-Inspired 01–12
- 许可：随 Lightroom / Camera Raw 授权（只能在 Adobe 软件内使用）
- 格式：创意配置文件 `.xmp`（在应用包 `Contents/Resources/Settings/Premium/Style - Film/Profiles/`）
- 取用：无需下载，已随 LR 安装，在 Profile 浏览器的 Premium 分组
- 适配：✅ 开箱即用；也能当"元数据/基底配对"的正确范例来对照
- 核查：2026-09-18

### G'MIC / Pat David Film Emulation
- 许可：GPL / CC 系（随 G'MIC 与 GIMP 分发）
- 格式：G'MIC 预设（GIMP/Krita/digiKam 内用）
- 取用：装 G'MIC-Qt；命令行 `gmic image.jpg -film_emulation …`
- 适配：⚠️ 不产出 .cube/HaldCLUT 给别的软件；只作 GIMP 内路线或"外观参考"
- 核查：2026-09-18

### darktable t3mujinpack
- 许可：预设集（仓库内说明）
- 格式：`.dtstyle`（**参数化**：Lab 曲线 + 通道混合）
- 取用：`git clone https://github.com/t3mujinpack/t3mujinpack`
- 适配：❌ **不能转成 LUT**（不是查表而是参数）——只能在 darktable 里用；若要复刻需手工近似
- 核查：2026-09-18

### abpy/FujifilmCameraProfiles
- 许可：**未声明**（⚠️ 仅个人使用）
- 格式：dcp / LUT（Fuji 官方胶片模拟的逆向匹配，562★）
- 取用：`git clone https://github.com/abpy/FujifilmCameraProfiles`
- 适配：⚠️ 技术上可用，但许可上不做再分发路径
- 核查：2026-09-18

### jeremieLouvaert/ComfyUI-Darkroom
- 许可：**未声明**（⚠️ 仅个人使用）
- 格式：ComfyUI 节点（号称 161 个卷 + Capture One 曲线数据 + H&D 曲线/颗粒/halation）
- 取用：ComfyUI 自定义节点安装
- 适配：⚠️ 面向 AI 出图工作流；导出 LUT 后理论上可进交付层，但要先解决许可
- 核查：2026-09-18

### ACES / OpenDRT（电影印片与影调映射）
- 许可：ACES 开源（其许可证）／OpenDRT 开源
- 格式：DCTL / OFX / OCIO 配置（Kodak 2383/2393 印片仿真等）
- 取用：ACES 官方仓库 / OpenDRT 发布页
- 适配：⚠️ 解决的是"曝光→显示映射 / 印片感"，**不是某一卷胶片**；作为影调映射层另议
- 核查：2026-09-18

---

## 附：格式 → 能否进交付层

| 格式 | 能否 | 路径 |
|---|---|---|
| `.cube`（33³/65³） | ✅ | 直接 `calibrate → lut-to-ccprofile` |
| HaldCLUT PNG/TIFF | ✅ | 同上（编码器直接读，自动识别 level） |
| 创意配置文件 `.xmp`（含 RGBTable） | ✅ | 已是目标格式，只需确认元数据与基底配对 |
| `.clf`（ACES CLF） | ⚠️ | 需先降级成 3D LUT（注意它工作在线性域） |
| `.dcp`（相机配置文件） | ⚠️ | 是相机色彩校准，不是风格 LUT；只在需要相机匹配时用 |
| `.dtstyle` / 参数化预设 | ❌ | 不是查表，无法转 LUT |
| G'MIC 预设 | ❌ | 同上（除非先导出为 HaldCLUT） |
