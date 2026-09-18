# Adobe RGBTable 二进制格式（创意配置文件内嵌 LUT）

> 这份规范是从**真实文件**逆出来的，并用两种独立实现交叉验证过：
> ① 解 Fujifilm 包的 `Velvia.xmp` 与 Adobe 自带的 `Nikon Z 50 2 Camera Carbon.xmp`；
> ② 按本文规范自己编码再用独立解码路径解回，误差 0.5/65535（纯取整）。
> 参考实现：`scripts/lut-to-ccprofile.py`（编码 + 解码）。

---

## 1. 外层：XMP 结构与字段

创意配置文件（`crs:PresetType="Look"`）里 LUT 以**属性**形式存在：

```xml
crs:RGBTable="470BB281E22C2206F337E79D332189A7"           ← table 的 ID = MD5(解压后的表内容)
crs:Table_470BB281E22C2206F337E79D332189A7="Lir00$C]jO…"  ← base85 文本
```

**ID 约定（已在上游文件上验证）**：`crs:RGBTable` 的值 = **解压后二进制表的 MD5 大写十六进制**。
对 Fujifilm `Velvia.xmp` 与 Adobe 自带 `Nikon Z 50 2 Camera Carbon.xmp` 实测都成立。
本工具链早期用随机十六进制（LR 也能正常加载），现已改为按此约定生成。

配套还有：`crs:CameraProfile`（基底配置文件）+ `crs:CameraProfileDigest`（其摘要）、
`crs:Name/ShortName/SortName/Group/Description`。
wrapper 预设用 `<crs:Look crs:Name="…" crs:Amount="1" crs:UUID="…" crs:Stubbed="true"/>` 引用它。

## 2. 编码链（四层）

```
base85 文本（自定义字母表，5 字符 → 4 字节小端）
   ↓
u32 未压缩长度 + zlib 压缩流
   ↓
二进制表：表头 + 16bit 样本 + 元数据
```

### 2.1 base85（不是标准 Ascii85）
- 字母表 85 个字符（**剔除** `" & , ; < > \ _ ~`，这样能安全放进 XML 属性）：
  `0-9`、`a-z`、`A-Z`，再加按固定顺序排列的标点。
- 数字映射是**自定义顺序**，不是 ASCII 顺序：
  `0-9`→0-9，`a-z`→10-35，`A-Z`→36-61，然后
  `.`62 `-`63 `:`64 `+`65 `=`66 `^`67 `!`68 `/`69 `*`70 `?`71 `` ` ``72 `'`73 `|`74
  `(`75 `)`76 `[`77 `]`78 `{`79 `}`80 `@`81 `%`82 `$`83 `#`84
- 每组 5 个字符组成一个 **little-endian** 32 位字：`value = d0 + d1·85 + d2·85² + d3·85³ + d4·85⁴`
  → `value.to_bytes(4, "little")`
- 结尾不足 5 字符的组输出 `n-1` 个字节（2 字符→1 字节，3→2，4→3）

### 2.2 zlib 层
base85 解出的字节流 = `u32 未压缩长度（LE）` + `zlib 流`。解压后长度必须等于声明的长度
（实测 Fujifilm Velvia：声明 196652 = 实际 196652 ✓）。

### 2.3 二进制表
```
u32 type = 1
u32 version = 1
u32 dimensions          # 1 或 3（3 = 三维表）
u32 divisions           # 每轴采样数（Adobe 常用 16 / 32）
samples[divisions³][3]  # u16 LE，顺序 r 外层 → g → b 内层
u32 primaries
u32 gamma
u32 gamut
f64 min_amount
f64 max_amount
[u32 flags]             # 可选
```

**样本是 delta 编码的**（相对中性斜坡）：
```
nop[i]   = (i * 0xFFFF + (divisions >> 1)) // (divisions - 1)      i ∈ [0, divisions)
stored   = (actual - nop[对应轴索引]) & 0xFFFF
actual   = (stored + nop[轴索引])     & 0xFFFF
```
三个通道分别用各自轴的 `nop`：R 轴 `ri`、G 轴 `gi`、B 轴 `bi`。
索引顺序：`idx = (ri * N + gi) * N + bi`。

### 2.4 采样（宿主如何用它）
输入归一化到 0..1 → 乘 `(N-1)` → 取相邻两点 → **三线性插值**（8 个角）。
即它就是一个标准 16bit 3D LUT，输入输出都在表格所使用的**那一个空间**里。

## 3. 元数据字段决定"用哪个空间解释这张表"（最容易错的地方）

实测统计（扫本机所有 `crs:RGBTable` 文件）：

| 来源类型 | 基底配置文件 | 元数据 `(primaries, gamma, gamut, min, max)` |
|---|---|---|
| Fujifilm 创意配置包（线性基底） | `Adobe Standard Linear` | **`(3, 1, 0, 1.0, 1.0)`** |
| Adobe 自带相机创意配置（普通基底） | `Camera Standard` / `Adobe Standard` | **`(1, 3, 0, 0.0, 1.0)`** |

**两者不能混用**：把"为线性域画的表"标成 `(1,3,…)`（或反过来），LR 会按错误空间解释，
典型症状就是**整张发灰、直方图挤向一侧**。

所以本工具链固定成两族：

| 族 | 表格空间 | 元数据 | 基底 |
|---|---|---|---|
| `--space display` | 显示域（sRGB 编码进 / 出） | `(1,3,0,0.0,1.0)` | `Adobe Standard` |
| `--space linear` | 线性域 | `(3,1,0,1.0,1.0)` | `Adobe Standard Linear` |

我们的源 LUT（spektrafilm / spectral_film_lut / RT 集合）都是 **sRGB 编码进 / 出**，
所以主路径用 `--space display`。

## 4. 用工具复现/自检

```bash
# 结构自检：编码 → 解回 → 比对（误差应 ≤ 0.5/65535）
bash scripts/selftest.sh

# 解一个现成文件看表头（判断它属于哪一族）
python3 - <<'EOF'
# 把下面存成 probe.py，用 python3 probe.py <某个.xmp> 运行
import re, sys, importlib.util
XMP = sys.argv[1]
spec = importlib.util.spec_from_file_location("cc", "scripts/lut-to-ccprofile.py")
cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
payload = re.search(r'crs:Table_[0-9A-F]+="([^"]+)"', open(XMP, encoding="utf-8").read()).group(1)
table, div = cc.decode_table(payload)
print("divisions:", div, "网格:", table.shape)
EOF
```

## 5. 常见误判

- **`--check-lut` 说 .cube "Invalid" 是正常的**：RawTherapee/ART 的 Film Simulation 只吃 HaldCLUT，
  不是所有 LUT 读取器都认 `.cube`。转成 HaldCLUT PNG 即可（`cube-to-hald.py`）。
- **别拿 `.dcp` 当风格 LUT**：它承载相机色彩校准（矩阵/色调曲线），不是"某一卷胶片的外观"。
- **不要手改 Table 文本**：它是压缩+自定义编码的，改坏了 LR 会直接忽略该 profile（不报错，只是不生效）。
