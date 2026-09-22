---
name: film-sim-delivery
description: 把胶片模拟外观（.cube LUT / HaldCLUT PNG / 光谱模拟烘出来的卷 / 开源 LUT 库里的风格）交付到真实修图工作流里——Lightroom Classic / Adobe Camera Raw 的「创意配置文件（creative profile）」、ART 的 CLUT、或直接批量处理图片。Use this skill whenever the user mentions 胶片模拟、胶片色、film simulation、Portra/Velvia/Kodachrome/Tri-X/HP5 等胶片卷名，或者抱怨「套上胶片配置后发灰/偏暗/高光被压平/颜色不对」，或者想把一批 .cube 装进 Lightroom/ART、想从开源 LUT 库里挑素材、想自己烘某个胶片卷。不适用于：相机自带配置文件缺失或相机匹配（那是 .dcp 相机校准问题）、视频调色与视频 LUT、以及纯通用后期（加颗粒暗角、抠图、格式转换）。
---

# 胶片模拟交付（film-sim delivery）

把「一个胶片外观」变成「装进用户真正在用的软件里、且亮度/高光正确」的成品。
本 skill 只负责**交付层**：拿到 LUT → 标定 → 转目标格式 → 安装 → 验收。

**这份文件的第一优先级是"别把用户的文件弄坏"和"别误报完成"**，其次才是怎么做得好。
原理、格式细节、来源调研都在 `references/` 里（见 §9）。

## 0. 六条硬约束（先读完再动手）

1. **原地覆盖必须显式**。`lr-filmsim.py` 默认**拒绝**运行，除非你给出 `--out <新目录>` 或显式
   `--in-place`。向用户交付图片时默认用 `--out`；`--in-place` 只在用户明确要求原地改时用，
   并且它会自动写时间戳备份。**永远不要**为了"省事"加 `--in-place`。
2. **安装前必须先看清单，再装**。装配置文件前先跑 `list` 或 `install --dry-run`；
   目标目录里若有同名文件且内容不同，脚本会**拒绝执行**并退出（需要 `--force` 才覆盖，覆盖前自动备份）。
   **不要**直接 `--force`——先把冲突念给用户听，**得到用户确认**后再动手；覆盖前会自动备份，
   `remove` 也会把被覆盖的旧文件恢复回来。
3. **零产物 = 失败**。生成器在"生成 0 个"时返回非零退出码并且不写任何文件。
   如果你看到"生成 0 个"，**不要**报告成功：它意味着输入没被识别（见下一条）或参数写错。
4. **文件名默认全都处理，不存在"名字不在表里就被跳过"**。`lut-to-ccprofile.py` 默认处理任意
   `.cube`/`.png`/`.tif` 文件名（`--only-known` 才会按内置表过滤）。客户文件名叫
   `Client Look 01.cube`、`Warm Soft.cube` 都会正常生成。
   文件名里的 `&` `<` `>` `"` `'` 会被正确转义，且每个写出的 XMP 都会用标准 XML 解析器复读校验——
   校验失败的文件会被删掉，不会留半成品。
5. **标定与生成必须同口径**。生成时 `--calibration` 里记录的 `mode`/`protect` 与本次命令不一致，
   脚本**直接拒绝**（不是提醒）。标定时 `--protect 0.68`，生成时也要 `--protect 0.68`，否则重跑标定。
6. **验收凭证要真算，不要手填**。用 `verify-delivery.py` 从产物算出 `verification.json`；
   结果分三态：`pass` / `partial`（有项缺输入没算，退出码 3，**不等于通过**）/ `fail`。
   不要把示例数字抄进去，也不要声称验证了没验证的东西。

## 1. 什么时候用、什么时候不用

**用**：用户要某个胶片外观落到具体工具里（Lightroom/ACR 创意配置文件、ART/RawTherapee HaldCLUT、
直接批处理图片），或者抱怨套上之后发灰/偏暗/高光被压平，或者想从开源库里挑/烘胶片 LUT。

**不用**（礼貌说明并转走，不要硬套本 skill 的流程）：
- 相机配置文件缺失、机型匹配问题 → 那是 `.dcp` 相机校准，不是胶片外观。
- 视频调色、视频 LUT → 本 skill 处理的都是静态图片。
- 纯通用后期（加颗粒、暗角、抠图、格式转换）→ 与胶片交付无关。
- 只是想要 Lightroom 的普通预设（曝光/对比度那种）→ 不需要 LUT 链路。

## 2. 环境与路径（命令一律按 skill 根目录定位）

**不要假设当前工作目录**。先确定两件事再动手：

```bash
SKILL_ROOT=/absolute/path/to/film-sim-delivery   # 本 skill 的根目录（含 SKILL.md）
export FILMSIM_ROOT=/absolute/path/to/film-work  # 素材与产物的工作根目录
python3 -m venv "$SKILL_ROOT/.venv" && "$SKILL_ROOT/.venv/bin/pip" install -r "$SKILL_ROOT/requirements.txt"
PY="$SKILL_ROOT/.venv/bin/python"                # 之后一律用绝对路径调用脚本
```

- 装依赖前**先问用户**是否允许装（这条属于会改变他机器状态的操作）。
- 素材（LUT 本体、成品配置）**不进 skill 目录**，都放 `FILMSIM_ROOT` 下。
- 命令里的 `scripts/xxx.py` 一律写成 `"$SKILL_ROOT/scripts/xxx.py"`。

## 3. 决策树

```
用户想干什么？
├─ 「把这个 LUT 装进 Lightroom / 做成配置文件」 → §4 主线
├─ 「套上后发灰 / 偏暗 / 高光被压平」          → §6 诊断修复
├─ 「批量给一批图套胶片」                      → §5-A
├─ 「在 ART / RawTherapee 里用」               → §5-B
├─ 「只能给预设，装不了配置文件」              → §5-C
└─ 「我要某个胶片（Portra/Velvia/黑白…）」     → §7 取素材
```

## 4. 主线：LUT → Lightroom 创意配置文件

```bash
# 1) 体检：反相 / 高光压死 / 相纸配错的 LUT 先挑出来
"$PY" "$SKILL_ROOT/scripts/qa-luts.py" --dir "$FILMSIM_ROOT/luts"

# 2) 逐卷标定（算 pre-gain），护高光阈值一起算进去
"$PY" "$SKILL_ROOT/scripts/calibrate-luts.py" --dir "$FILMSIM_ROOT/luts" \
      --mode brightness --protect 0.68 --out "$FILMSIM_ROOT/luts/_calibration.json"

# 3) 生成创意配置文件 + wrapper 预设（默认支持任意文件名）
"$PY" "$SKILL_ROOT/scripts/lut-to-ccprofile.py" --dir "$FILMSIM_ROOT/luts" \
      --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
      --out "$FILMSIM_ROOT/lr-ccprofiles" \
      --space display --protect 0.68 --mode brightness --label "护高光"

# 4) 先看清单，确认没有冲突
"$PY" "$SKILL_ROOT/scripts/install_ccprofiles.py" list --src "$FILMSIM_ROOT/lr-ccprofiles"
"$PY" "$SKILL_ROOT/scripts/install_ccprofiles.py" install \
      --src "$FILMSIM_ROOT/lr-ccprofiles" --dry-run
#    确认无误后再真正装（会写备份与清单 manifest）
"$PY" "$SKILL_ROOT/scripts/install_ccprofiles.py" install \
      --src "$FILMSIM_ROOT/lr-ccprofiles"

# 5) 真算验收凭证
"$PY" "$SKILL_ROOT/scripts/verify-delivery.py" \
      --profile "$FILMSIM_ROOT/lr-ccprofiles/<名字>.xmp" \
      --lut "$FILMSIM_ROOT/luts/<名字>.cube" \
      --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
      --out "$FILMSIM_ROOT/lr-ccprofiles/verification.json"
```

**强度（Amount）**：`--bake-strength 0.5` 把强度烘进表里（产出的配置本身就是 50% 强度）；
`--amounts 1,0.75,0.5,0.25` 会额外生成几个 1KB 级的 wrapper 预设，它们**共用同一张表**、
只是 `crs:Amount` 不同——这是 Adobe/Fujifilm 官方预设的同款结构，比按强度烘 N 张表省得多。
直接套图路径用 `--strength 0.5`，语义一致（都是与输入线性混合）。

**`--space` 必须与基底配置文件配对**：`display` → 基底 `Adobe Standard` + 元数据 `(1,3,0,0.0,1.0)`；
`linear` → 基底 `Adobe Standard Linear` + 元数据 `(3,1,0,1.0,1.0)`。配错的典型症状是"整张发灰"，
细节见 `references/rgb-table-format.md` §3。

**告诉用户三件事**：① 重启 Lightroom / ACR 后在配置文件浏览器里找对应分组；
② 他还需要相机对应的 `*.dcp` 基础配置文件，否则配置文件不会出现；
③ 本仓库只能证明文件已就位与表内容正确，**不能证明他的 Lightroom 真的接受它**——
必须让他在真实 RAW 上测一下。

## 5. 支线

**A. 直接套图（不进 Lightroom）**

```bash
# 写入新目录（默认姿势；原图不动）
"$PY" "$SKILL_ROOT/scripts/lr-filmsim.py" --lut "$FILMSIM_ROOT/luts/xxx.cube" \
      --out "$FILMSIM_ROOT/rendered" --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
      --protect 0.68 照片/*.tif

# 只在用户明确要求"原地改"时才这么写（自动写 .filmsim-backups/ 时间戳备份）
"$PY" "$SKILL_ROOT/scripts/lr-filmsim.py" --lut "$FILMSIM_ROOT/luts/xxx.cube" --in-place 照片/a.tif

# 批量试版 + 拼对比图
"$PY" "$SKILL_ROOT/scripts/try-looks.py" 照片.tif --lut-dir "$FILMSIM_ROOT/luts" --out 对比图
```

`lr-filmsim.py` 也吃 HaldCLUT PNG（自动识别 level，超大网格自动降采样）。
**`apply-look.sh` 与 `try-looks.py` 不是等价主路径**：它们不吃 `--calibration`，也不套用与
配置文件一致的护高光口径；`apply-look.sh` 的默认 `PRE_GAIN=0.3472` 只是 spektrafilm 的兜底值。
需要「逐卷标定 + 同口径护高光」就用 `lr-filmsim.py --calibration --protect`，wrapper 只适合快速试版。

**注意已知的输出保真边界**：原地/写盘都会丢失 TIFF 元数据、丢弃 alpha 与额外通道、
不做 ICC 转换、灰度图按红通道还回。这些在 `references/pitfalls.md` 与 README 的
Limitations 一节有完整列表——**在动手处理用户的原始文件前先跟他讲清楚**。

**B. ART / RawTherapee**

本仓库**只提供** `.cube → HaldCLUT PNG` 这一步：

```bash
"$PY" "$SKILL_ROOT/scripts/cube-to-hald.py" --dir "$FILMSIM_ROOT/luts" --out "$FILMSIM_ROOT/hald" --level 8
```

ART 的 CLUT 目录、加工配置（`.arp`）、spektrafilm 实时桥接**都需要在 ART 里手工配置**，
本仓库不含这些脚本，也不代劳。已知的坑记在 `references/pitfalls.md` §5–§6
（external-3dLUT 的 `command` 必须是纯 ASCII 路径；Film Simulation 只吃 HaldCLUT）。
宿主假设与未测情形见 `references/hosts.md`。

**C. 只能给预设（参数化近似）**

```bash
"$PY" "$SKILL_ROOT/scripts/lut-to-xmp.py" --dir "$FILMSIM_ROOT/luts" --out "$FILMSIM_ROOT/lr-presets"
```

只认内置 `TASTE` 表里的 8 个胶片名，其他名字会被跳过（跳过不等于成功：零产物时脚本返回失败）。
**必须告知用户：这是参数化近似，不是编码后的 3D LUT。仓库尚未建立可复现的保真度评分方法，
因此不提供保真度百分比。** 原因是 3D LUT 的跨通道色相扭转 LR 表达不了。

## 6. 诊断：套上后不对，怎么查

| 症状 | 先查 | 判据 |
|---|---|---|
| 整张发灰、对比低 | 表空间 ↔ 元数据 ↔ 基底是否三者配对 | 用 `verify-delivery.py` 看 `metadata_matches_space` / `base_profile_matches_space` |
| 偏暗/偏亮 | pre-gain 是否逐卷标定过 | `brightness_ratio` 应在 0.95–1.05；共用系数必错 |
| 高光发白/没细节 | 有没有做护高光、protect 是否与标定一致 | `white_out` ≥250；合成 fixture 上未护高光纯白会落到 0–220 |
| 颜色整个反了 | 相纸配错（正片配了负片相纸） | `qa-luts.py` 会直接标红（对比度为负） |
| 某些卷偏、某些卷正常 | 共用了同一个 pre-gain | 逐卷标定后应一致 |

```bash
"$PY" "$SKILL_ROOT/scripts/qa-luts.py" --dir "$FILMSIM_ROOT/luts"
"$PY" "$SKILL_ROOT/scripts/verify-delivery.py" --profile "<交付的.xmp>" --out /tmp/v.json
```

诊断结论要落到**可复算的数字**上（哪一项、修前多少、修后多少），不要只给形容词。

## 7. 取素材

**先读 `references/sources.md`**（来源 × 许可 / 格式 / 覆盖 / 取用命令），
需要新来源时按 `references/sourcing-playbook.md` 的流程走——**许可闸门**与**抽检**不能跳。

```bash
bash "$SKILL_ROOT/scripts/fetch_sources.sh" --list      # 列出可拉取的来源
bash "$SKILL_ROOT/scripts/fetch_sources.sh" spectra     # spectral_film_lut（MIT）
bash "$SKILL_ROOT/scripts/fetch_sources.sh" rt          # RawTherapee HaldCLUT（约 402MB，CC BY-SA 4.0）
```

**下载或安装任何外部东西之前要单独获得用户同意**（几百 MB、联网、可能装软件）。
边界：可以下载/转换/派生并回写来源表；**不要**把 LUT 数据、完整文件枚举、许可全文打包进 skill；
不要用无许可证的库做再分发来源。

## 8. 验收与凭证

```bash
"$PY" "$SKILL_ROOT/scripts/selftest.py"        # 最小闭环：造 LUT → 标定 → 转配置 → 解回 → 护高光断言
```

对真实交付，用 `verify-delivery.py` 生成 `verification.json`（放在交付目录里）。
它的判定分成三类，**报告时必须区分**：

| 类别 | 含义 | 怎么处理 |
|---|---|---|
| `verdict: pass`（退出码 0） | 必需项全部由脚本复算并通过 | 可以据报告成功 |
| `verdict: partial`（退出码 3） | 算出来的都过了，但有指标**缺输入没算** | **这不是通过**。补 `--lut`/`--calibration`/`--images`；本次确实不需要图片级验收才加 `--allow-partial` |
| `verdict: fail`（退出码 1） | 有指标不达标，或声明了 `--require-images` 却没给图片 | **不要报告成功**；修参数、重新标定或补图片 |

判定规则：**没有复算 ≠ 通过**。`unrecomputed` 里的项在任何情况下都不能算作达标。

可复算项：表 ID = 表内容 MD5、元数据/基底配对、灰阶响应、中灰、纯白；
给 `--lut` 可复算编码往返误差 `decode_error_lsb`；
给 `--images <真实照片>` 可复算亮度比 / 最亮 5% 中位 / ≥250 占比 / 高光细节 std。

**图片级阈值是两段式判定的**：原图自己达到绝对目标时按**绝对目标**判（更严）；原图本身就达不到时，
才退到「保留率」下限（如 ≥250 占比不低于原图的 80%），并写进 `thresholds_used.basis`。
两条都保证同一件事：**输出不得比原图差**。

**参考阈值不是历史实测值**：`references/calibration.md` §0 说明哪些数字是未归档的历史报告值、
CI 到底证明了什么范围。不要把它们说成"实测结果"。

## 9. 失败处理与恢复

| 情况 | 怎么办 |
|---|---|
| "生成 0 个" | 视为失败。检查输入目录（只扫顶层、不递归）、文件扩展名、`--only-known`/`--only` 是否误用 |
| 标定口径不一致被拒 | 按本次 `--protect` 重跑 `calibrate-luts.py`，不要绕过检查 |
| 安装被冲突拦住 | 把冲突文件名念给用户，确认是他原有配置后再 `--force`（会自动备份） |
| 装错了要回滚 | `install_ccprofiles.py remove`：**被覆盖过的旧文件从备份恢复**，新增的删除；被外部改过或备份缺失时中止而不是硬来。先跑 `--dry-run` 看它打算恢复/删哪些 |
| 原图被原地改坏 | 备份在源文件同目录 `.filmsim-backups/<名字>.<时间戳>.bak` |
| 输出的 XMP 让 LR 报错 | 生成器会先做 XML 复读；若仍异常，用 `verify-delivery.py` 查表 ID 与元数据配对 |
| 宿主不认产物 | 只能给用户排查清单（基础 dcp、重启、RAW 还是 JPEG）；**这一步仓库无法替他验证** |

## 10. 目录与脚本索引

```
scripts/
├── lut-to-ccprofile.py     ★ 主线：任意 .cube/.png/.tif → Adobe RGBTable（XMP + wrapper），零产物即失败
├── calibrate-luts.py       ★ 逐卷标定 pre-gain（midgray / brightness，配 --protect）
├── install_ccprofiles.py   ★ 安装/卸载：dry-run、冲突检测、备份、manifest、精确回滚
├── verify-delivery.py      ★ 从产物真算 verification.json（区分「已复算」与「算不出来」）
├── qa-luts.py              ★ 体检：反相/压死/错配
├── lr-filmsim.py             套图核心（--out / --in-place、--calibration、--protect）
├── try-looks.py              批量试版 + 拼对比图
├── cube-to-hald.py           .cube → HaldCLUT PNG（给 ART / RawTherapee）
├── lut-to-xmp.py             退路：反解成 LR 近似预设（只认 8 个内置名）
├── bake-spectral-luts.py     用 spectral_film_lut 烘卷（可选依赖）
├── curate-rt-halclut.py      从 RT 集合挑卷
├── fetch_sources.sh          列/拉上游素材（联网，需先问用户）
├── install-lr-ccprofiles.sh  install_ccprofiles.py 的 POSIX 包装
├── apply-look.sh             按简写名套图（POSIX 包装）
└── selftest.py / selftest.sh 最小闭环自检
```

references/：`calibration.md`（标定与护高光 + §0 数值来源与证据状态）· `rgb-table-format.md`（表格二进制格式）·
`pitfalls.md`（7 条硬坑）· `hosts.md`（宿主/系统/相机适配与未测情形）· `verification-schema.md`（凭证格式）·
`sources.md`（来源与许可）· `sourcing-playbook.md`（调研流程）

## 11. 可移植性与未验证部分（诚实清单）

- **脚本**：Python 3.9+，macOS / Windows / Linux 都有 CI 覆盖（合成场景）。`*.sh` 只是 POSIX 包装，
  原生 Windows 请用对应的 `.py` 入口。
- **宿主**：Lightroom / ACR / ART / RawTherapee 的**实际加载未被 CI 验证**——CI 只验证产物结构、
  表的可解码性与合成影调。Capture One / Affinity / darktable 未验证。
- **相机**：脚本不含任何机型假设（`crs:CameraModelRestriction` 留空），
  但基底配置文件 `Adobe Standard` / `Adobe Standard Linear` 必须存在于用户机器上。
- **语言**：正文中文；完整英文说明见仓库根目录 `README.md`（中文版 `README.zh.md`），
  与源码不一致时以源码为准。
