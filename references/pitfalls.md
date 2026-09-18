# 7 条硬坑（都来自实际交付中的失败）

> 这些不是"注意事项"，是会让交付**直接失败或明显出错**的东西。每条都给了症状 → 根因 → 修法。

---

## 1. Lightroom 根本不支持 .cube / HaldCLUT

- **症状**：让用户"导入 LUT"时，LR 里找不到入口；用户说"我导入不了"。
- **根因**：LR Classic / ACR 只认**配置文件**：`.dcp`（相机校准）+ **XMP 创意配置文件**（内嵌 RGBTable LUT）。
- **修法**：走 `lut-to-ccprofile.py` 生成 XMP 创意配置文件 + wrapper 预设，装到
  `…/Adobe/CameraRaw/Settings/`。想要"叠加式预设"才用 `lut-to-xmp.py`（参数化近似，不是编码后的 3D LUT；仓库尚未建立可复现的保真度评分方法，因此不提供保真度百分比）。

## 2. 表格元数据必须与基底配置文件配对

- **症状**：整张发灰、对比骤降、直方图挤向一侧。
- **根因**：把"线性域画的表"标成显示域的元数据（或反之），宿主按错误空间解释 → 相当于多转一次 gamma。
- **修法**：`--space display` ↔ 元数据 `(1,3,0,0.0,1.0)` ↔ 基底 `Adobe Standard`；
  `--space linear` ↔ `(3,1,0,1.0,1.0)` ↔ 基底 `Adobe Standard Linear`。详见 `rgb-table-format.md` §3。

## 3. 每个 LUT 的曝光定位不同，不能共用 pre-gain

- **症状**：某些卷正常、某些卷明显偏亮或偏暗；黑白卷尤其暗。
- **根因**：不同项目的 LUT 白点定位不同——spektrafilm 是"源白点 +4 档"（内部增益 2.88，须乘 0.3472 抵消）；
  spectral_film_lut 的中灰落在 140–155；RT 集合里从 111 到 153 都有；黑白卷甚至落在 ~99。
- 早期文档报告过范围为 0.40–1.67 的历史值，但该批 LUT 的清单、哈希与完整校准输出未随仓库保存，
  属**未归档的历史报告值，未纳入 CI**（见 `calibration.md` §0）。对当前输入重新标定，不要沿用该范围。
- **修法**：`calibrate-luts.py` 逐卷二分求根；生成时用 `--calibration` 读入。

## 4. 不做护高光，纯白会被明显压低

- **症状**："高光被切掉了/发白没细节"。CI 在**合成 fixture** 上验证的断言是：未做护高光时纯白输出
  明显受压，范围 0–220（`evals/make_fixtures.py`），坏样本 ≤215（`evals/grade.py`）。
- 早期文档另记有"最亮 5% 从 248 掉到 208、≥250 占比 0%、细节 std 从 6.1 掉到 1.0"，
  以及具体的 "~209"——这些属**未归档的历史报告值**（见 `calibration.md` §0），
  既不能代表所有 LUT，当前 CI 也不复算。
- **根因**：胶片印片肩部的白点约 0.82，所有高光挤在一个天花板下。
- **修法**：`--protect 0.68`——按输入亮度加权，`L≤0.68` 用 LUT，`0.68→1.0` smoothstep 混回原始，
  `L=1.0` 时输出=输入（这一步可由代码公式直接复核）。修完的具体指标
  （"最亮 5% 回到 247、≥250 占 3.3%、细节 5.1"）属未归档的历史报告值，见 `calibration.md` §0。

## 5. ART 的 external-3dLUT `command` 必须是纯 ASCII 路径

- **症状**：ART 报 `Color/Tone Correction - Invalid LUT parameters for: …/ART_spektrafilm.json`，
  但文件看着没毛病。
- **根因**：命令字符串里含非 ASCII（如中文目录）时 ART 无法执行；JSON 本体放在中文目录没问题，
  `//` 注释也没问题——**只有 command 路径**必须 ASCII。
- **验证**：中文 JSON + ASCII 命令 → 生效；中文命令 → 失效（对照实验过）。
- **修法**：把桥接启动器放到纯 ASCII 路径（如 `~/artclut/`），JSON 里指向它（`setup-art-bridge.sh`）。

## 6. ART / RawTherapee 的 Film Simulation 只吃 HaldCLUT

- **症状**：把 `.cube` 丢进 CLUT 目录，ART 检查器报 `Invalid LUT file`。
- **根因**：Film Simulation 工具是 HaldCLUT 专用的；`.cube` 得走别的入口（或转换）。
- **修法**：`cube-to-hald.py` 转成 HaldCLUT PNG（level 8 = 512×512 够用）；
  反过来在 Lightroom 侧不认 HaldCLUT，要 RGBTable——**两边格式不通，别混**。

## 7. 正片的相纸必须为 None，否则二次反相

- **症状**：套上正片（Velvia/Kodachrome/Provia/Ektachrome）后画面几乎全黑、颜色发红。
- **根因**：正片是"直接观看"，若再走负片相纸链路，等于反相两次。
- **实测**：`Velvia + Endura` → 黑=[179,180,177] 白=[5,3,2]（反相）；
  `Velvia + None` → 黑=[0,0,0] 白=[170,171,170]（正确）。
- **修法**：
  - spectral_film_lut：`print_film=None`（`bake-spectral-luts.py` 的 JOBS 里写 `None`）
  - ART 桥接：`Print paper` 选 `None`
  - spektrafilm 的 **CLI 强制要相纸** → 正片在它这条路上做不出来，改用上面两条
- **附带**：`qa-luts.py` 会把这类反相 LUT 直接标出来（对比度为负）——**交付前一定跑一次**。
