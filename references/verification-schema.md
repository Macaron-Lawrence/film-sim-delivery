# verification.json 格式（交付凭证）

> 每次交付都在交付目录写一份 `verification.json`。**验收只读这个文件 + 独立复核它的数字**，
> 不采信对话里的自述。原因：评测与复盘都需要可独立复算的凭证。
>
> ⚠️ 下面示例里的**每个数字都是占位示例，不是任何真实测量的记录**。
> 历史上这些示例值曾被误当作实测结果引用；写你自己的文件时请用当场算出来的值。

---

## 最小字段

```json
{
  "skill": "film-sim-delivery",
  "eval": "deliver-cube-to-lightroom",
  "inputs": { "lut": "/path/portra_like.cube", "divisions": 32 },

  "params": {
    "space": "display",
    "base_profile": "Adobe Standard",
    "metadata": [1, 3, 0, 0.0, 1.0],
    "pre_gain": 0.3991,
    "protect": 0.68
  },

  "outputs": {
    "profile": "/path/lr-ccprofiles/xxx.xmp",
    "wrapper": "/path/lr-ccprofiles/xxx wrapper.xmp",
    "table_id": "1C9898F07B85AAAF…"
  },

  "checks": {
    "decode_error_lsb": 0.5,
    "gray_response": {"0": 14.3, "32": 18.9, "64": 47.0, "96": 94.9, "128": 138.5,
                      "160": 172.2, "192": 193.8, "224": 218.1, "255": 255.0},
    "mid_gray_out": 138.5,
    "white_out": 255.0,
    "brightness_ratio": 0.977,
    "top5pct_median": 247.1,
    "pct_ge_250": 3.31,
    "highlight_detail_std": 5.06
  },

  "verdict": "pass"
}
```

## 硬性要求

| 字段 | 判据 |
|---|---|
| `params.space` ↔ `params.base_profile` ↔ `params.metadata` | 必须配对：`display`+`Adobe Standard`+`(1,3,0,0.0,1.0)`；`linear`+`Adobe Standard Linear`+`(3,1,0,1.0,1.0)` |
| `checks.decode_error_lsb` | ≤ 1.0（解回表 vs 源 LUT 的最大误差，单位 1/65535） |
| `checks.mid_gray_out` | 118–145（取决于标定模式：midgray≈128 / brightness≈138） |
| `checks.white_out` | ≥ 250（护高光生效） |
| `checks.brightness_ratio` | 0.95–1.05 |
| `checks.top5pct_median` | ≥ 240（原图亮度前 5% 像素的输出亮度**中位数**；字段名即定义，早期行文误写作"均值"） |
| `checks.pct_ge_250` | ≥ 2.5 |
| `checks.highlight_detail_std` | ≥ 3.5 |
| `outputs.table_id` | = 交付表内容的 MD5（大写十六进制） |

## 复核方式（评分器怎么用它）

1. 读 `verification.json`；
2. **独立**解出 `outputs.profile` 里的 RGBTable，重算 `gray_response` / `mid_gray_out` / `white_out` /
   `decode_error_lsb`，与文件里声明的数字比对（防止"写了数字但没做"）；
3. 再对阈值判定。

注意评分器**只从交付表重算** `gray_response` / `mid_gray_out` / `white_out` / `decode_error_lsb`；
`brightness_ratio` / `top5pct_median` / `pct_ge_250` / `highlight_detail_std` 这四项它按你声明的值判阈值，
**不从源图复算**——所以这四项尤其要靠你自己如实测。

所以：**数字必须是真算出来的**。声明与独立复核差得太多，等同于没做验证。

## 缺字段怎么办

- 少写字段 → 该条判为未通过（评分器按缺失处理，不会猜）。
- 某个指标确实无法测（例如没有真实照片）→ 用合成场景测，并在 `notes` 里写明用了什么场景，
  但**不要省略字段**。
