# film-sim-delivery

**An Agent Skill that delivers a film look into a real photo workflow** —
`LUT → exposure calibration → target format → install → verification`.

A host-agnostic [Agent Skill](https://agentskills.io): drop the folder into any
skills directory (Claude Code / Codex / DSH / anything that reads `SKILL.md`),
or just use the scripts as a plain CLI. No host-specific APIs.

*[中文说明见下文](#中文说明)*

---

## The problem this solves

Film simulation is easy to *look at* and surprisingly hard to *deliver*.
Four failure modes eat almost all the time:

| Symptom | Real cause | Fix in this skill |
|---|---|---|
| "I have a `.cube`, how do I load it into Lightroom?" | **Lightroom / Camera Raw cannot import LUTs at all** — there is no such entry point. | Encode the LUT into an Adobe **creative profile** (`crs:RGBTable` inside an XMP): `scripts/lut-to-ccprofile.py` |
| Washed out, flat, grey image after applying a profile | **space ↔ metadata ↔ base-profile mismatch.** `display` must pair with `Adobe Standard` + `(1,3,0,0.0,1.0)`; `linear` with `Adobe Standard Linear` + `(3,1,0,1.0,1.0)`. Any other combination double-applies gamma. | `references/rgb-table-format.md` + the encoder asserts the pairing |
| "It's ~20 % darker than my reference" | No per-LUT **exposure calibration**. The required gain spans **0.40–1.67** across sources; one shared value is always wrong for some stock. | `scripts/calibrate-luts.py` (bisection on mid-grey or brightness) |
| Whites capped, highlights flat and detail-less | Film **print shoulder** rolls off to ~209/255. Highlight *detail* std collapses from 6.10 to 1.02. | Highlight protection baked into the table (`--protect 0.68`) |

Measured on 6 real ARW files (Apple-engine renders): unprotected LUT gives
brightness ratio 0.915 / top-5 % 207.6 / 0 % of pixels ≥ 250 / highlight-detail
std 1.02; with protection, 0.986 / 247.1 / 3.31 % / 5.06 — against 1.000 / 248.1
/ 4.27 % / 6.10 for the untreated original.

## Install

The repository root **is** the skill, so cloning it into a skills directory is all
it takes:

```bash
# use your host's skills path (Claude Code ≈ ~/.claude/skills, DSH ≈ ~/.dsh/skills, …)
git clone https://github.com/Macaron-Lawrence/film-sim-delivery.git \
          ~/.claude/skills/film-sim-delivery
```

Then just talk to the agent — 「把 `$FILMSIM_ROOT/luts` 里的卷做成 Lightroom 创意配置文件」,
or 「我套上胶片配置后发灰、偏暗，帮我看」. Nothing else to register: the host reads
`SKILL.md` (`name` + `description`) and pulls in `references/` and `scripts/` only
when the task needs them.

Prefer a plain CLI? The scripts run standalone — see Quick start below. Nothing in
this repo calls a host-specific API.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FILMSIM_ROOT=/path/to/your/library     # your LUTs live in $FILMSIM_ROOT/luts

# 1) sanity-check the LUTs (inverted / crushed / mismatched tables)
python3 scripts/qa-luts.py --dir "$FILMSIM_ROOT/luts"

# 2) calibrate exposure per LUT, together with highlight protection
python3 scripts/calibrate-luts.py --dir "$FILMSIM_ROOT/luts" \
        --mode brightness --protect 0.68 --out "$FILMSIM_ROOT/luts/_calibration.json"

# 3) build Adobe creative profiles (+ wrapper presets)
python3 scripts/lut-to-ccprofile.py --dir "$FILMSIM_ROOT/luts" \
        --calibration "$FILMSIM_ROOT/luts/_calibration.json" \
        --out "$FILMSIM_ROOT/lr-ccprofiles" \
        --space display --protect 0.68 --label "HP" --group "Film Simulation"

# 4) install (macOS / Windows / Linux paths are auto-detected)
python3 scripts/install_ccprofiles.py install
#    restart Lightroom → Profile browser → your group

# 5) self-test: build a LUT → calibrate → encode → decode → assert
python3 scripts/selftest.py
```

English walkthrough: [`references/README.en.md`](references/README.en.md).

## Repo layout

```
SKILL.md                  # the skill itself (frontmatter + decision tree + SOP)
scripts/                  # 15 CLI tools: encode, calibrate, convert, install, QA, selftest
references/               # 8 deep-dive docs (format, pitfalls, calibration, hosts, sources…)
assets/                   # calibration.example.json
evals/                    # 3 eval tasks + grader + fixtures + trigger queries
```

| Script | Purpose |
|---|---|
| `lut-to-ccprofile.py` | **main encoder** — `.cube` → Adobe creative profile (XMP + embedded RGBTable, base85 + zlib, delta-encoded samples) |
| `calibrate-luts.py` | per-LUT exposure solve (bisection, `midgray` or `brightness` mode) |
| `install_ccprofiles.py` | cross-platform install of profiles/presets into CameraRaw |
| `lr-filmsim.py` | apply a look directly to images (`.cube` + HaldCLUT, TIFF16 in/out) |
| `cube-to-hald.py` | `.cube` → HaldCLUT PNG for ART / RawTherapee |
| `lut-to-xmp.py` | curve-only fallback preset (retains ~80 %; use when a DCP is unavailable) |
| `qa-luts.py` | table quality report (monotonicity, clipping, range, identity deviation) |
| `selftest.py` | end-to-end self-test of the encoder/decoder round trip |
| `bake-spectral-luts.py`, `curate-rt-halclut.py`, `fetch_sources.sh` | bake spectral simulations, curate RT HaldCLUTs, fetch sources |

## Host / OS / camera coverage

See [`references/hosts.md`](references/hosts.md) for the full matrix and an honest
"not covered" list. Short version:

- **Lightroom Classic / Camera Raw** → creative profiles (this pipeline).
- **ART / RawTherapee** → HaldCLUT PNG (`scripts/cube-to-hald.py`).
- **Photoshop / Resolve / any node pipeline** → hand over the `.cube` directly, or batch-process with `scripts/lr-filmsim.py`.
- **macOS / Windows / Linux** → all Python entry points work everywhere; `*.sh` are POSIX wrappers (on native Windows call the `.py` entry points).
- **Cameras** → nothing is camera-specific except that the base profile (`Adobe Standard` for `display`, `Adobe Standard Linear` for `linear`) must exist for your body. Profiles are generated with `crs:CameraModelRestriction` empty, so they are not tied to a model.

## Verification is a product, not a claim

Deliveries ship a `verification.json`
([schema](references/verification-schema.md)) with decodable evidence: the
embedded table's gray-scale response, per-pixel highlight statistics, and the
exact parameters used. `evals/grade.py` reads **only artifacts**, independently
re-decodes the table and recomputes the numbers, then compares them with what was
declared — so "I verified it" without real numbers does not pass.

## Evals

Three tasks — deliver a look, diagnose a space mismatch, diagnose missing
highlight protection — graded by artifacts, not by prose. Fixtures are
**synthetic** (a generated `portra_like.cube` plus two deliberately broken
profiles) and ship in `evals/fixtures/`:

```bash
python3 evals/make_fixtures.py                 # regenerate fixtures
python3 evals/grade.py <run_dir> --eval 2      # grades against evals/fixtures by default
```

Reported measurements from the skill's own test rounds (with-skill vs hard-isolated
baseline):

| Measurement | with-skill | baseline |
|---|---|---|
| Diagnose "missing highlight protection" (task C) | **9/9** | 4/10 |
| Diagnose "space mismatch" (task B) | **5/5** | 4/5 |
| Trigger accuracy, 20 mixed queries | recall **10/10**; 19/20 overall → after description fix, spot-check 5/5 | — |

The grader deliberately is not a prose checker: it re-decodes the RGBTable from
the produced XMP and re-runs the arithmetic, and it records a hard `0` with a
reason when a candidate's table cannot be decoded at all (that happened to one
baseline, which emitted a payload that is not a valid Adobe table).

## Licence

MIT — see [`LICENSE`](LICENSE). This repo bundles **no LUT data**; all fixtures
are synthetic and generated by `evals/make_fixtures.py`. The open LUT libraries
listed in [`references/sources.md`](references/sources.md) keep their own licences
(MIT / CC BY-SA 4.0 / GPLv3 / …) — check them before redistributing anything you
bake with this tooling.

---

## 中文说明

**把胶片外观交付进真实修图工作流**的 Agent Skill：
`LUT → 曝光标定 → 目标格式 → 安装 → 验收`。

通用的 Skill 格式（`SKILL.md` + `scripts/` + `references/`），不依赖任何特定宿主；
Claude Code / Codex / DSH 都能装，也可以纯粹当命令行工具用。

**它解决的问题**（都是实际踩出来的）：

1. **Lightroom 根本不支持 .cube / HaldCLUT** —— 必须做成 Adobe 创意配置文件（XMP 内嵌 RGBTable），
   这条没有别的入口。编码器 `scripts/lut-to-ccprofile.py` 负责把 `.cube` 烘成可用的 XMP。
2. **套上就发灰** —— 九成是「表所在色彩空间 ↔ 元数据 ↔ 基底配置文件」三者对不上：
   `display` 配 `Adobe Standard` + `(1,3,0,0.0,1.0)`，`linear` 配 `Adobe Standard Linear` + `(3,1,0,1.0,1.0)`，
   错配会让宿主多（或少）做一次 gamma。
3. **偏亮/偏暗** —— 每个卷的曝光定位都不同，实测需要 0.40–1.67 的增益跨度，
   必须逐卷标定（`scripts/calibrate-luts.py`，二分求根）。
4. **高光被切平** —— 胶片印片肩部会把纯白压到 ~209，高光细节标准差从 6.10 掉到 1.02；
   用 `--protect 0.68` 把高光按权重混回原图（0.986 / 247.1 / 细节 5.06）。

**怎么用**：先把仓库 clone 成技能目录（见上面的 Install），
然后直接用自然语言说「把 `$FILMSIM_ROOT/luts` 里的卷做成 Lightroom 创意配置文件」，
或「我套上胶片配置后发灰、偏暗，帮我看」。
中文细节全在 `SKILL.md` 与 `references/`，脚本也可以脱离 agent 单独跑（Quick start 步骤 1–5）。

**验收不是口头承诺**：交付必须带 `verification.json`（内含可解码的实测数据），
`evals/grade.py` 只读产物、独立解码表并重算数字——没有真实数字的"我验证过了"过不了评测。

**许可证**：本仓库 MIT。**不打包任何 LUT 数据**，评测样本是 `evals/make_fixtures.py`
生成的合成样本；`references/sources.md` 里列的开源 LUT 库各自保留其许可证。
