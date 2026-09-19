# film-sim-delivery

*[English](README.md) · 中文*

`film-sim-delivery` 是一个 [Agent Skill](https://agentskills.io)，同时是一组**独立可用的 Python 工具**，用于把静态图片的胶片外观真正交付出去。它能解析并施加 LUT、标定曝光落点、把 LUT 转成 Adobe 创意配置文件或 HaldCLUT 图像、安装生成的 XMP、拼对比图、抓取或筛选素材、跑合成自检。

本仓库**不是** LUT 合集、不是 raw 转换器、不是相机配置文件生成器，也不是视频色彩管理系统。仓库里只有一份用于测试的合成 `.cube` 样本，不含任何第三方 LUT 合集。Adobe 各应用、ART、RawTherapee、Resolve，以及第三方基底配置文件，都不随仓库分发。

## 支持的工作流

| 工作流 | 状态与边界 |
|---|---|
| Adobe 创意配置文件 | 由 `scripts/lut-to-ccprofile.py` 实现。它把重采样后的 3D LUT 以 Adobe `RGBTable` 形式内嵌进 XMP，并写一个包装预设。**默认处理任意文件名**（`--only-known` 才按内置名表过滤），名字里的 XML 特殊字符会被转义、写出的每个文件都用标准解析器复读，**零产物时返回非零退出码**而不是报告成功。Lightroom、Camera Raw、Bridge、Photoshop 的**实际加载未经 CI 验证**。所需的基底配置文件必须已存在于 Adobe 宿主里。 |
| `.cube` 转 HaldCLUT | 由 `scripts/cube-to-hald.py` 实现。输出 8 位 PNG，支持 `.cube` 的 1D shaper。面向 ART 与 RawTherapee 的 Film Simulation，但**宿主加载未经 CI 验证**。 |
| 直接处理图片 | 由 `scripts/lr-filmsim.py` 实现，支持 `.cube` 与 HaldCLUT 输入。TIFF 族走 `tifffile`，其他 Pillow 支持的格式走 Pillow。**原地覆盖不再是默认行为**：不给 `--out DIR` 或不显式写 `--in-place` 就拒绝运行；输出目录里已有同名文件时不给 `--overwrite` 就拒绝覆盖；任何原地写入前都会先写时间戳备份。`--calibration` 复用逐卷标定增益，`--protect` 与配置文件路径共用同一套护高光口径。`scripts/apply-look.sh` 是 POSIX 便捷包装。 |
| 近似 XMP 预设 | 由 `scripts/lut-to-xmp.py` 实现，覆盖 8 个硬编码胶片名。它推导色调曲线、HSL、颜色分级、饱和度、自然饱和度、颗粒、锐化、降噪、暗角参数。这是**近似**，不是编码的 3D LUT，且**没有建立可信的保真度百分比**。 |
| 曝光标定 | 由 `scripts/calibrate-luts.py` 实现。用二分法对每个 LUT 求 `pre_gain`，目标可以是中点，也可以是中性灰渐变带的加权亮度。处理顶层 `.cube`、`.png`、`.tif` 文件。 |
| 安装与卸载 | 由 `scripts/install_ccprofiles.py` 实现；`scripts/install-lr-ccprofiles.sh` 在 POSIX 系统上包装它。`list` 与 `install --dry-run` 先给计划；会覆盖同名但内容不同的文件时**直接中止，除非显式 `--force`**；被覆盖的旧文件备份到 `.filmsim-backup/<时间戳>/`；每次安装都更新 `.filmsim-manifest.json`；`remove` **只删清单里记录、且 SHA-256 仍匹配**的文件。**不安装 DCP 基底配置文件**。 |
| 基础 LUT 质检 | 由 `scripts/qa-luts.py` 实现。报告抽样中点、白点、黑点与对比度，并标记灰度响应偏弱或反相的情况。它**不**检测单调性、截断、色域范围，也不测与恒等变换的偏差。 |
| 拼对比图 | 由 `scripts/try-looks.py` 实现。把顶层 `.cube` 与 `.png` LUT 施加到一张 Pillow 可读的图片上，输出 JPEG 预览并拼成带标注的 JPEG 大图。 |
| 素材抓取与筛选 | `scripts/fetch_sources.sh` 列出或下载指定的上游来源。`scripts/curate-rt-halclut.py` 从 RawTherapee HaldCLUT 树里复制指定子集或全部 PNG。这些流程受上游许可证约束，并可能占用大量磁盘与带宽。 |
| 光谱 LUT 烘焙 | `scripts/bake-spectral-luts.py` 驱动可选的 `spectral_film_lut` 包，执行内置任务列表。这条路径是可选的，**仓库 CI 不覆盖**。 |
| 样本、评分与自检 | `evals/make_fixtures.py` 生成确定性的合成样本。`evals/grade.py` 对另外产出的评测产物打分，并**自己复算**能算的项（包括从 fixture LUT 重新推导 `decode_error_lsb`，而不是采信声明值）。`evals/test_safety.py` 断言上面的安全行为；`evals/test_grader.py` 断言评分器对已知正确交付仍给满分、产物缺失时仍会失败。`scripts/selftest.py` 检查一条合成的标定 + Adobe 表格编解码路径。这些都是**内部检查，不是宿主集成测试**。 |

## 依赖要求

独立 Python 工具需要：

- Python 3.9 或更新
- `numpy>=1.21`
- `Pillow>=9.0`
- `tifffile>=2021.11.2`

版本声明在 [`requirements.txt`](requirements.txt)。仓库**没有 lockfile、没有 Python 包元数据、没有可安装的控制台入口**。脚本请从仓库检出目录里直接运行。

部分工作流有额外要求：

- `*.sh` 包装脚本需要 Bash。原生 Windows 用户请改用有对应 Python 入口的那些命令。
- `scripts/fetch_sources.sh` 的相应分支需要 `git`、`curl`、`unzip`。
- `spektra` 分支需要 `uv`。`spectra` 分支可用 `uv`，也可用 `venv` + `pip`。
- `scripts/bake-spectral-luts.py` 需要另外安装的 `spectral_film_lut` 包。它当前的兼容性要求与本仓库无关。
- 想让 agent 自动发现这个技能，需要一个兼容 Agent Skills 的宿主。Python 工具本身不依赖任何 agent 运行时。

Adobe 创意配置文件还依赖 Adobe 宿主，以及宿主能解析到的基底相机配置文件。编码器默认值如下：

| 编码空间 | Adobe 表格元数据 | 默认基底配置文件 |
|---|---|---|
| `display` | `(1, 3, 0, 0.0, 1.0)` | `Adobe Standard` |
| `linear` | `(3, 1, 0, 1.0, 1.0)` | `Adobe Standard Linear` |

这些 DCP 文件**不由脚本提供**。`Adobe Standard Linear` 通常需要为对应相机另行获取配置文件。即便 `Adobe Standard`，是否可用也取决于宿主与相机。生成的 XMP 里 `crs:CameraModelRestriction` 为空，**并不能**免除基底配置文件的要求。

## 安装

### 作为 Agent Skill 使用

把仓库 clone 或复制到你的 agent 宿主会扫描的技能目录，然后按该宿主的技能安装说明操作。仓库根目录包含 [`SKILL.md`](SKILL.md)，配套材料在 [`references/`](references/)，可执行工具在 [`scripts/`](scripts/)。

clone 只是**让技能文件可用**。技能执行的任何命令仍然需要 Python 与上面的依赖，外加输入 LUT 和宿主相关的前置条件。

```bash
git clone https://github.com/Macaron-Lawrence/film-sim-delivery.git
cd film-sim-delivery
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows 上请使用对应的虚拟环境激活方式或解释器路径。

### 作为独立命令行工具使用

clone 仓库、建环境、装 `requirements.txt`，然后按路径调用脚本。**没有**名为 `film-sim-delivery` 的可执行文件可供安装。

```bash
git clone https://github.com/Macaron-Lawrence/film-sim-delivery.git
cd film-sim-delivery
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/selftest.py
```

## 用任意 LUT 库快速上手

编码器内置一份硬编码的 `NAMES` 映射，用于生成显示名，但**默认处理任意文件名**——那张表只是用来把显示名写好看些。`--only-known` 才会按表过滤。生成零个配置文件是**失败**而不是静默成功：命令返回非零退出码，并把已经写出的半成品删掉，因此「跳过」不会再被当成「转换完成」。

脚本**只扫描指定目录本身，不递归子目录**。下面这个例子使用一个显式指定的工作库：

```bash
export FILMSIM_ROOT=/absolute/path/to/film-work
mkdir -p "$FILMSIM_ROOT/luts"
# 先把你的 .cube 或 HaldCLUT .png/.tif 文件复制到 $FILMSIM_ROOT/luts

python3 scripts/qa-luts.py \
  --dir "$FILMSIM_ROOT/luts"

python3 scripts/calibrate-luts.py \
  --dir "$FILMSIM_ROOT/luts" \
  --mode brightness \
  --protect 0.68 \
  --out "$FILMSIM_ROOT/luts/_calibration.json"

python3 scripts/lut-to-ccprofile.py \
  --dir "$FILMSIM_ROOT/luts" \
  --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
  --out "$FILMSIM_ROOT/lr-ccprofiles" \
  --space display \
  --protect 0.68 \
  --group "Film Simulation" \
  #（不需要 --allow-unknown：任意文件名默认都处理；要按内置名表过滤才加 --only-known）
```

标定与生成配置文件要使用**相同**的 `--protect` 值。编码器会读取标定 JSON 里的 `pre_gain`，但**不会校验** JSON 中记录的 `mode` 与 `protect` 是否与本次调用一致。

安装前必须先看一眼。安装器遇到同名但内容不同的文件会**直接中止**（除非 `--force`），覆盖前会备份，所以这一步不要跳：

```bash
python3 scripts/install_ccprofiles.py list \
  --src "$FILMSIM_ROOT/lr-ccprofiles"

python3 scripts/install_ccprofiles.py install \
  --src "$FILMSIM_ROOT/lr-ccprofiles" \
  --dry-run
```

然后安装到显式指定的 Adobe 设置目录，或让安装器自行选择平台默认路径：

```bash
python3 scripts/install_ccprofiles.py install \
  --src "$FILMSIM_ROOT/lr-ccprofiles"
```

重启 Adobe 宿主，并用有代表性的 raw 文件实测。**仅凭生成的 XMP，仓库无法证明宿主兼容性。**

## 面向任务的工作流

### 直接施加一个 LUT

`lr-filmsim.py` **不再默认原地替换**：必须选一个落盘位置——`--out DIR` 写新文件，原地改写要显式 `--in-place`（会先写时间戳备份）。建议同时传 `--calibration` 让每个卷用自己的标定增益，并传与生成配置文件时相同的 `--protect`，这样两条交付路径才是同一套色调口径。

```bash
python3 scripts/lr-filmsim.py \
  --lut "$FILMSIM_ROOT/luts/look.cube" \
  --out "$FILMSIM_ROOT/rendered" \
  --suffix _look \
  --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
  --protect 0.68 \
  --strength 0.75 \
  photo.tif photo.jpg
```

不处理图片、只看 LUT 信息：

```bash
python3 scripts/lr-filmsim.py \
  --lut "$FILMSIM_ROOT/luts/look.cube" \
  --info
```

线性到线性的 LUT 加 `--linear-pipeline`。对带 `LUT_1D_SIZE` 的 `.cube`，解析器会先施加 shaper 再查 3D 表。

POSIX 包装支持 LUT 名模糊匹配与一层目录批处理：

```bash
FILMSIM_ROOT=/absolute/path/to/film-work \
PRE_GAIN=1.0 \
bash scripts/apply-look.sh look \
  --out "$FILMSIM_ROOT/rendered" \
  --strength 0.75 \
  photos/
```

### 生成 HaldCLUT

```bash
python3 scripts/cube-to-hald.py \
  --dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/hald" \
  --level 8 \
  --pre-gain 1.0
```

Level 8 产出 512 × 512、8 位 RGB PNG，每通道 64 个采样点。脚本会拒绝每通道网格超过 128 的 level。生成的 PNG 请用目标宿主自己的 CLUT 设置去安装或选择。

### 生成近似的 Lightroom 预设

```bash
python3 scripts/lut-to-xmp.py \
  --dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/lr-presets" \
  --group "Film Simulation" \
  --pre-gain 1.0
```

只有出现在脚本 `TASTE` 表里的文件名会被处理。未知名字会被跳过，因为脚本没有兜底的颗粒与暗角配方；**零产物时脚本返回失败**。产物是**参数化预设**，不是通用的 3D LUT 转换。

### 在一张图上比较多个外观

```bash
python3 scripts/try-looks.py photo.jpg \
  --lut-dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/contact-sheets" \
  --only portra ektar \
  --size 1400 \
  --cols 3 \
  --pre-gain 1.0
```

它会为每个外观写一张 JPEG，以及一个名为 `对比图.jpg` 的拼图。预览路径会把输入转成 8 位 RGB，**不保留其元数据**。

### 抓取并筛选素材

下载任何东西之前，先列出可用的辅助分支：

```bash
bash scripts/fetch_sources.sh --list
```

RawTherapee 分支会下载并解压一个很大的归档：

```bash
FILMSIM_ROOT=/absolute/path/to/film-work \
SRC_DIR=/absolute/path/to/downloads \
bash scripts/fetch_sources.sh rt

python3 scripts/curate-rt-halclut.py \
  --src /absolute/path/to/downloads/HaldCLUT \
  --dst "$FILMSIM_ROOT/luts/rt"
```

筛选命令加 `--list` 可以只统计匹配到的条目、不复制。`--all` 会复制它找到的全部 PNG，并从源路径推导输出名。重新分发下载或派生的文件之前，请先看 [`references/sources.md`](references/sources.md) 与 [`references/sourcing-playbook.md`](references/sourcing-playbook.md)。

### 用 `spectral_film_lut` 烘焙 LUT

请在已安装该可选包的解释器里运行：

```bash
python3 scripts/bake-spectral-luts.py --list
python3 scripts/bake-spectral-luts.py \
  --out "$FILMSIM_ROOT/luts/spectral" \
  --size 33 \
  --only velvia trix
```

脚本通过上游库写出 sRGB 输入、Rec. 709 输出的 `.cube`。它的 `--noise` 开关**目前被解析但未使用**。

### 卸载已安装的创意配置文件

卸载把源目录当作文件名清单：删除目标目录中同名的文件，其他文件一律不动。

```bash
python3 scripts/install_ccprofiles.py remove \
  --src "$FILMSIM_ROOT/lr-ccprofiles"
```

如果源 XMP 文件已经不在了，安装器就**没有任何记录**可以用来卸载。

## 脚本索引

| 入口 | 输入与输出 | 主要选项 | 副作用与校验 |
|---|---|---|---|
| `scripts/lut-to-ccprofile.py` | 顶层 `.cube` / `.png` / `.tif` LUT → 配置文件 XMP + 包装 XMP | `--dir`, `--out`, `--only`, `--only-known`, `--divisions`, `--space`, `--base-profile`, `--base-digest`, `--pre-gain`, `--calibration`, `--group`, `--protect` | 默认处理任意文件名。创建输出目录，覆盖同名 XMP。解码每张编码后的表（误差 < 1 个 16 位 LSB），并用 XML 解析器复读每个写出的文件，失败即删除。标定口径（`mode`/`protect`）与本次不一致时拒绝运行。**零产物返回非零退出码。不测 Adobe 宿主。** |
| `scripts/calibrate-luts.py` | 顶层 LUT 文件 → JSON | `--mode`, `--protect`, `--merge`, `--out` | 写 JSON。二分法**假定**得分在增益 0.10–4.0 区间单调，且不检查是否成功夹住区间。`--merge` 会保留已有的无关记录。 |
| `scripts/lr-filmsim.py` | `.cube` 或 HaldCLUT + 图片 → 处理后的图片 | `--out`, `--in-place`, `--overwrite`, `--calibration`, `--protect`, `--suffix`, `--strength`, `--linear-pipeline`, `--pre-gain`, `--info` | **必须显式选择落盘位置**；原地写入一定先备份（`.filmsim-backups/`）；输出重名默认拒绝。使用原子临时文件替换。 |
| `scripts/cube-to-hald.py` | 顶层 `.cube` → HaldCLUT PNG | `--level`, `--pre-gain`, `--only`, `--out` | 创建输出目录，覆盖同名 PNG。**不做往返比对。** |
| `scripts/lut-to-xmp.py` | 已知的顶层 `.cube` → 近似预设 XMP | `--group`, `--only`, `--pre-gain`, `--out` | 创建或覆盖 XMP。未知 stem 跳过，且零产物时返回非零退出码。名字经 XML 转义，写出的文件会复读校验。**不测 Adobe 宿主。** |
| `scripts/qa-luts.py` | 顶层 `.cube` 与 `.png` LUT → 控制台报告 | `--dir`, `--only` | 只读。抽样一条固定灰度探针，基于黑白对比与白点水平给出二值启发式结论。 |
| `scripts/try-looks.py` | 一张 Pillow 可读图片 + 顶层 `.cube` / `.png` LUT → JPEG 预览与拼图 | `--lut-dir`, `--only`, `--out`, `--size`, `--cols`, `--strength`, `--linear-pipeline`, `--pre-gain` | 创建输出文件，覆盖重名文件。这是**目视参考材料，不是数值质检**。 |
| `scripts/install_ccprofiles.py` | 源 XMP 目录 → Adobe 设置目录 | `list`, `install`, `remove`, `--src`, `--dest`, `--dry-run`, `--force`, `--no-backup` | install 覆盖前先备份并更新清单；遇到同名但内容不同的文件会中止整次运行（除非 `--force`）。remove 按清单精确回滚，有文件被改动过就整次中止。**不改动 DCP 文件。** |
| `scripts/install-lr-ccprofiles.sh` | 安装器的 POSIX 包装 | `--list`, `--remove`；第一个参数之后的其余参数透传 | 副作用与 Python 安装器相同。默认执行 install。 |
| `scripts/apply-look.sh` | LUT 名模糊匹配 + 文件或目录 → 直接处理 | `--ls`, `--out`, `--strength`, `--suffix`, `--linear-pipeline`, `--pre-gain`, `--flat` | 因为它委托给 `lr-filmsim.py`，**可能覆盖图片**。目录搜索只深入一层。需要常见 POSIX 工具。 |
| `scripts/fetch_sources.sh` | 具名上游来源 → 下载或安装工具 | `--list`, `rt`, `spectra`, `fuji`, `spektra` | 需要联网。可能下载数百 MB、覆盖式解压、创建虚拟环境、clone 仓库或安装工具。 |
| `scripts/curate-rt-halclut.py` | RawTherapee HaldCLUT 树 → 复制出的 PNG 子集 | `--src`, `--dst`, `--all`, `--list` | 即使在 `--list` 模式下也会创建目标目录，并覆盖重名的已复制文件。**不跑 LUT 质检。** |
| `scripts/bake-spectral-luts.py` | 内置光谱胶片任务 → `.cube` | `--out`, `--size`, `--only`, `--list`, `--noise` | 导入并执行第三方 `spectral_film_lut`；在输出目录写入。`--noise` 无效果。 |
| `scripts/verify-delivery.py` | 交付的配置文件（+ 可选源 LUT / 标定 / 真实照片）→ `verification.json` | `--profile`, `--lut`, `--calibration`, `--pre-gain`, `--protect`, `--images`, `--declare`, `--out` | 只读输入，只写输出 JSON。所有非 null 的 check 都由它算出；算不出来的列在 `unrecomputed`，**不作为通过**。图片级指标以现场图片为额外下限，绝不比绝对目标更宽松。 |
| `scripts/selftest.py` | 生成的合成 LUT → 临时标定与 XMP 产物 | `--work` | 不给 `--work` 时，成功后删除其临时目录。检查表格 MD5 约定、编解码误差、中点与被保护的白点。 |
| `evals/test_safety.py` | 临时工作区 → 通过/失败报告 | — | 断言：不给 `--in-place` 不会原地写；不会静默覆盖；零产物退出非零；任意文件名与 XML 特殊字符可用；安装冲突会中止；回滚按清单精确执行；标定口径不一致会被拒；文档不引用不存在的脚本。 |
| `evals/test_grader.py` | 造一个已知正确的候选并打分 | — | 断言评分器给它满分、删掉产物后不再满分、且真的复算了 `decode_error_lsb`。 |
| `scripts/selftest.sh` | `scripts/selftest.py` 的 POSIX 包装 | 参数透传 | 校验内容与 Python 自检相同。 |
| `evals/make_fixtures.py` | 合成生成器 → 提交风格的样本树 | `--out`, `--verify-reproducible` | 写入或覆盖样本。检查缺陷签名；可复现模式会比对两棵生成的树。 |
| `evals/grade.py` | 一次外部评测运行目录 → 控制台或 JSON 评分 | `--eval`, `--fixtures`, `--no-fixtures`, `--json` | 除非给 `--json`，否则只读。解码候选配置文件并检查声明的评测产物；**它不是通用的交付验证器**。 |
| `evals/assemble_review.sh` | 评测运行目录 → 评审目录与可选 HTML | 可选的工作区参数 | 复制评测产物，并可能调用外部技能评审生成器。会读取 `VIEWER` 与 `VIEWER_PY`。 |

## 转换是怎么做的

### LUT 解析与施加

共享实现位于 `scripts/lr-filmsim.py`。

- `.cube` 解析器读取 `LUT_3D_SIZE`、可选 `LUT_1D_SIZE`，以及 `DOMAIN_MIN` / `DOMAIN_MAX`。
- 完整的 1D shaper 会在 3D 查表之前做线性插值。**不完整的 shaper 会被忽略。**
- 3D 查表把归一化坐标截断到 0–1，并在八个相邻采样点上做三线性插值。
- HaldCLUT 的维度由方形图片的像素数反推。反推出的网格过大时会先降采样。
- `pre_gain` 把 sRGB 值解码到线性光、相乘、再编码回去，然后才进 LUT。
- `strength` 把 LUT 结果与未修改的输入块线性混合。命令行**不截断**传入的强度值。

### 标定与高光保护

`calibrate-luts.py` 采样 19 个中性值，在 0.10–4.0 的增益区间上二分 40 次。`midgray` 瞄准最接近 0.5 的采样值；`brightness` 瞄准中性渐变带上的加权平均。

当 `--protect` 大于 0 时，标定与 Adobe 表格生成都会把高亮度区域的 LUT 输出按 smoothstep 过渡混回输入。**阈值不是自动选出来的**，两条命令必须传同一个值。

### Adobe RGBTable 编码

`lut-to-ccprofile.py` 把输入 LUT 重采样成立方表，每通道量化到 16 位，再相对一条中性斜坡做差分编码。随后把表与其空间元数据序列化、用 zlib 压缩，并用 Adobe 自定义 base85 字母表编码成 XMP 属性。未压缩表的**大写 MD5** 用作表格 ID。

对 `display`，采样得到的 LUT 接收的是显示编码值。对 `linear`，编码器会把表输入转成 sRGB 再施加源 LUT，然后把结果转回线性。空间元数据与具名基底配置文件必须按上面的依赖表成对出现。

编码器输出一个创意配置文件 XMP，以及一个引用该配置文件 UUID 的普通预设。**这些是生成出来的文件，不等于 Adobe 宿主接受了它们。**

## 配置与环境变量

| 变量 | 使用者 | 行为 |
|---|---|---|
| `FILMSIM_ROOT` | 大多数转换、筛选、抓取、包装与安装脚本 | 设定工作根目录。未设置时脚本使用当前工作目录。若个脚本会先找 `数据/luts` 再找 `luts`。可复用的工作流里，显式的 `--dir` / `--out` / `--src` / `--dst` 更稳妥。 |
| `LR_SETTINGS_DIR` | `scripts/install_ccprofiles.py` | 覆盖 Adobe CameraRaw `Settings` 目标目录。 |
| `XDG_CONFIG_HOME` | `scripts/install_ccprofiles.py` | 在非 macOS、非 Windows 系统上组成默认 Adobe 设置路径。未设置时用 `~/.config`。 |
| `APPDATA` | `scripts/install_ccprofiles.py` | 在 Windows 上组成默认 Adobe 设置路径。未设置时用 `~/AppData/Roaming`。 |
| `SRC_DIR` | `scripts/fetch_sources.sh` | 覆盖素材下载与环境目录。未设置时用 `$FILMSIM_ROOT/sources`；`FILMSIM_ROOT` 也未设置时用 `$PWD/sources`。 |
| `PRE_GAIN` | `scripts/apply-look.sh` | 设定该包装的 pre-gain。未设置时用 `0.3472`。这是**包装的默认值，不是任意 LUT 的通用值**。 |
| `VIEWER` | `evals/assemble_review.sh` | 外部 `generate_review.py` 的显式路径。未设置时脚本会探测三个用户级技能位置。 |
| `VIEWER_PY` | `evals/assemble_review.sh` | 外部评审工具偏好的 Python 解释器，要求 Python 3.10 或更新。 |

部分默认路径仍保留旧的 `数据` 目录布局。特别是标定的默认输出、筛选的默认源与目标，与新版的 `luts`、`sources`、`lr-ccprofiles` 布局并不一致。自动化里请使用显式路径。

## 测试与验证

跑本地合成测试：

```bash
python3 scripts/selftest.py
```

自检会创建一个合成的 17 格 LUT、标定它、构建带高光保护的显示域创意配置文件、解码内嵌表、检查其 MD5 派生的 ID 与量化误差，并断言中点与白点响应。它**不会**打开 Lightroom、Camera Raw、Photoshop、ART、RawTherapee 或 Resolve。

[CI 工作流](.github/workflows/ci.yml) 在 Ubuntu、macOS、Windows 上以 Python 3.9 与 3.12 运行，它会：

1. 安装 `requirements.txt`；
2. 用 `ast` 解析每个 Python 入口；
3. 运行 `scripts/selftest.py`；
4. 重新生成合成样本并检查其缺陷签名；
5. 验证样本生成是字节可复现的；
6. 运行 `evals/test_safety.py`（不覆盖、不误报成功、不引用幽灵脚本）；
7. 运行 `evals/test_grader.py`（评分器对已知正确交付仍满分、产物缺失时仍失败）。

CI **不测试**第三方下载、光谱烘焙、原生 Windows 上的 shell 包装，也不测试与任何图片或视频宿主的集成。

`verification.json` 由 `scripts/verify-delivery.py` 生成，标为已计算的项都是从产物算出来的（表 ID/MD5、元数据↔基底配对、灰阶响应、中灰、纯白；给 `--lut` 与 `--calibration` 时加上 `decode_error_lsb`；给 `--images` 时加上四项图片级指标）。**不给 `--images` 时它根本不计算图片级指标**——那几项一律记成 `null` 并列入 `unrecomputed`，所以示例值或上一次留下的数字**绝不能**当成本次交付的测量结果。

`evals/grade.py` 比一个完整的验证器要窄。在它的交付评测里，它会独立解码内嵌的 RGBTable、重算其 MD5、读取元数据与基底配置文件字段、评估灰度响应、检查包装预设的 UUID 是否匹配，并且用声明的参数从 fixture LUT **重造表**来自己推导 `decode_error_lsb`，而不是采信声明值。没有提供真实图片时，它不把声明出来的图片级指标当成证据。

[`references/verification-schema.md`](references/verification-schema.md) 描述评分器所期望的评测产物。请把它当作**人工或外部评测契约**，而不是编码器承诺的输出。

## 限制与破坏性操作

处理原始文件或安装配置文件之前，请先读这一节。

- `lr-filmsim.py` **不再默认覆盖**：不给 `--out DIR` 或 `--in-place` 就拒绝运行；原地写入前会在 `.filmsim-backups/` 写时间戳备份；输出目录里已有同名文件时必须显式 `--overwrite`。
- 安装器覆盖前会备份（`.filmsim-backup/<时间戳>/`），并把每次安装记入 `.filmsim-manifest.json`；遇到同名但内容不同的文件会**中止**，除非显式 `--force`。卸载按清单精确执行：只删 SHA-256 仍与安装时一致的文件，不一致则整次卸载中止。
- TIFF 写入**不保留 TIFF 元数据**。基于 Pillow 的写入在原本存在 ICC profile 时会保留它，但不保留一般 EXIF 或其他图像元数据。
- 图片处理只保留前三个通道，alpha 与额外通道被丢弃。灰度输入会被扩展成 RGB 处理，然后**取红通道**而不是按亮度还原。
- 图片工具假定 RGB 值是归一化的，**不做 ICC 色彩转换**。结果取决于喂给它的编码值。
- 生成的 XMP 会对文件名、标签、描述、组名做转义，并且每个写出的文件都用标准 XML 解析器复读；复读失败的会被删掉而不是留在盘上。属性里只转义 `&`、`<`、`>`、双引号——**故意不转义单引号**，因为表数据用的 Adobe base85 字母表里就含单引号。
- `lut-to-ccprofile.py` 默认处理任意文件名，`--only-known` 才按内置名表过滤。生成零个配置文件时**返回非零退出码**，跳过不会再被当成成功。
- 配置文件与它的包装预设都用 `--group`，自定义分组时这一对保持一致。
- 标定 JSON 记录了 `mode` 与 `protect`，编码器**会强制**它们一致：某条标定的 `protect` 与本次调用不符、或缺少 `protect`/`pre_gain` 字段，都会在写出任何文件之前中止；同一份标定里混用多种 `mode` 也会被拒。
- `--base-profile` 可以指定自定义配置文件，但 `--base-digest` 只在同时提供了 `--base-profile` 时才被使用。脚本**不校验**这两个值是否对应到已安装的 DCP 文件。
- `--protect`、`--strength`、`--pre-gain`、`--divisions` 以及若干尺寸值**仍然缺少完整的范围校验**。坏值可能导致无效输出、极端输出或运行时失败。（这轮安全修复覆盖的是破坏性默认与契约不一致，不是所有数值范围。）
- HaldCLUT TIFF 输入在部分核心路径里被接受，但质检与拼图的文件发现只包括 `.cube` 与 `.png`。各脚本的格式覆盖**并不一致**。
- `scripts/bake-spectral-luts.py --noise` **目前未使用**。
- 仓库在 [`references/hosts.md`](references/hosts.md) 里给出了宿主指引，但该文档**不能替代**对你要发布的那个具体宿主版本、操作系统、相机与基底配置文件的实测。

## 安全与隐私

常规的 LUT 转换、标定、直接图片处理、样本生成、评分与自检都在本地运行，**不上传图片、不调用远程服务**。

`scripts/fetch_sources.sh` 不同。它的 `rt`、`fuji`、`spectra`、`spektra` 分支会访问第三方服务，可能下载归档、clone 仓库或安装软件。请先审阅脚本与上游许可证。RawTherapee 归档按辅助脚本自己的描述，解压前约 **402 MB**。

## 仓库结构

```text
README.md                 英文主说明（本文件的中文版为 README.zh.md）
SKILL.md                  Agent Skill 指令
scripts/                  转换、标定、施加、安装、素材辅助
references/               格式说明、宿主说明、来源记录、评测 schema
assets/                   标定 JSON 示例
evals/                    合成样本、样本生成器、评分器、评审辅助
.github/workflows/ci.yml  跨平台合成 CI
requirements.txt          Python 依赖最低版本
LICENSE                   仓库代码许可证
```

延伸阅读：

- [`references/rgb-table-format.md`](references/rgb-table-format.md) 讲解 Adobe 表格布局。
- [`references/calibration.md`](references/calibration.md) 讨论预期的标定与高光保护模型。其 §0 把 **CI 能复算的** 与 **只有早期文档记录的** 数值分开列出；后者统一标注为**未归档的历史报告值，未纳入 CI**。
- [`references/hosts.md`](references/hosts.md) 记录宿主假设与未测情形。
- [`references/sources.md`](references/sources.md) 记录上游来源与许可证说明。
- [`references/sourcing-playbook.md`](references/sourcing-playbook.md) 给出素材审阅流程。
- [`references/pitfalls.md`](references/pitfalls.md) 汇总已知失败模式。深层文档里的一些较早断言，可能比当前的自动化覆盖更强；**以源代码和本 README 描述的行为为准**。看到深层文档引用具体数值时，先看它的来源标注——CI 无法复算的数字统一标为**未归档的历史报告值，未纳入 CI**。

## 许可证

仓库代码与文档以 [MIT License](LICENSE) 授权。

**不捆绑任何第三方 LUT 合集。** 仓库确实包含一份合成测试 LUT：[`evals/fixtures/luts/portra_like.cube`](evals/fixtures/luts/portra_like.cube)，以及 [`evals/fixtures/bad/`](evals/fixtures/bad/) 下生成的合成坏样本。从第三方获取的文件、数据集、配置文件、归档、包与工具，各自保留其许可证与条款。使用或再分发前请先核对这些条款。
