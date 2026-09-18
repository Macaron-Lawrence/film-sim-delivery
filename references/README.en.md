# film-sim-delivery — English quick start

A host-agnostic Agent Skill that **delivers a film look into a real photo workflow**:
`LUT → exposure calibration → target format → install → verification`.

The main body (`SKILL.md`) is written in Chinese; this file is the English summary.
Everything here is a plain CLI — no host-specific APIs.

---

## What it solves

| Problem | What this skill does |
|---|---|
| "I have a `.cube` film LUT, how do I use it in Lightroom?" | Lightroom/ACR **cannot import LUTs at all**. Encode the LUT into an Adobe **creative profile** (`crs:RGBTable` inside an XMP) — `scripts/lut-to-ccprofile.py` |
| "Everything looks washed out / too dark after applying a film profile" | Per-LUT **exposure calibration** (`scripts/calibrate-luts.py`) — the required gain ranges 0.40–1.67 across sources, so one shared value never works |
| "Highlights look clipped / flat, whites are capped" | **Highlight protection** baked into the table (`--protect 0.68`): film print shoulder caps pure white at ~209; this blends back to the input above the threshold |
| "It looks grey / flat overall" | Almost always a **space ↔ metadata ↔ base-profile mismatch**: `display` must pair with `Adobe Standard` + `(1,3,0,0.0,1.0)`; `linear` with `Adobe Standard Linear` + `(3,1,0,1.0,1.0)` (see `references/rgb-table-format.md`) |
| "Where do I even get film LUTs?" | `references/sources.md` (10 open sources with licences) + `scripts/fetch_sources.sh` |

## Quick start

```bash
# 0) dependencies
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FILMSIM_ROOT=/path/to/your/library      # LUTs live in $FILMSIM_ROOT/luts

# 1) sanity check the LUTs (detects inverted / crushed / mismatched tables)
python3 scripts/qa-luts.py --dir "$FILMSIM_ROOT/luts"

# 2) calibrate exposure per LUT (bisection), together with highlight protection
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

# 5) self-test (build a LUT → calibrate → encode → decode → assert)
python3 scripts/selftest.py
```

## Host / OS / camera coverage

See `references/hosts.md`. Short version:

- **Lightroom Classic / ACR** → creative profiles (this pipeline).
- **ART / RawTherapee** → HaldCLUT PNG (`scripts/cube-to-hald.py`).
- **Photoshop / Resolve / ComfyUI-style pipelines** → hand them the `.cube` directly,
  or batch-process images with `scripts/lr-filmsim.py`.
- **macOS / Windows / Linux** → all Python entry points work everywhere;
  `*.sh` files are just POSIX wrappers (on native Windows use the `.py` entry points).
- **Cameras** → nothing is camera-specific except that the base profile
  (`Adobe Standard` for `display`, `Adobe Standard Linear` for `linear`) must exist for your body;
  profiles are generated with `crs:CameraModelRestriction` empty, so they are not tied to a model.

## Verification is a product, not a claim

Deliveries must ship a `verification.json` (`references/verification-schema.md`).
The grader (`evals/grade.py`) reads **only artifacts**, independently recomputes the gray-scale
response by decoding the embedded table, and compares it with what was declared —
so "I verified it" without real numbers does not pass.

## Licence notes

LUT **sources** carry their own licences (MIT / CC BY-SA 4.0 / GPLv3 …), listed in `references/sources.md`.
This skill bundles **no LUT data** — only tooling and documentation.
