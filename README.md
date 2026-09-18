# film-sim-delivery

**English** · [中文说明](README.zh.md)

`film-sim-delivery` is an [Agent Skill](https://agentskills.io) and a collection of standalone Python utilities for delivering static-image film looks. It can parse and apply LUTs, calibrate exposure placement, convert LUTs to Adobe creative profiles or HaldCLUT images, install generated XMP files, build contact sheets, fetch or curate source material, and run synthetic checks.

This repository is not a LUT collection, a raw converter, a camera-profile generator, or a video color-management system. It includes one synthetic `.cube` fixture for tests, but no third-party LUT collection. Adobe applications, ART, RawTherapee, Resolve, and third-party base profiles are not bundled.

## Supported workflows

| Workflow | Status and limits |
|---|---|
| Adobe creative profiles | Implemented by `scripts/lut-to-ccprofile.py`. It embeds a resampled 3D LUT in XMP as an Adobe `RGBTable` and writes a wrapper preset. It processes **any** filename by default (`--only-known` restricts to the built-in name table), XML-escapes names and re-parses every file it writes, and **exits non-zero when it produces zero profiles** instead of reporting success. Actual Lightroom, Camera Raw, Bridge, and Photoshop loading is not tested in CI. The required base profile must already exist in the Adobe host. |
| `.cube` to HaldCLUT | Implemented by `scripts/cube-to-hald.py`. It writes an 8-bit PNG and supports a `.cube` 1D shaper. Intended for ART and RawTherapee Film Simulation, but host loading is not tested in CI. |
| Direct image processing | Implemented by `scripts/lr-filmsim.py` for `.cube` and HaldCLUT inputs. TIFF-family files use `tifffile`; other Pillow-supported formats use Pillow. **In-place overwriting is no longer the default**: the tool refuses to run without either `--out DIR` or an explicit `--in-place`, refuses to overwrite an existing output without `--overwrite`, and writes a timestamped backup before any in-place write. `--calibration` reuses the per-LUT gain and `--protect` the same highlight protection as the profile path. `scripts/apply-look.sh` is a POSIX convenience wrapper. |
| Approximate XMP presets | Implemented by `scripts/lut-to-xmp.py` for eight hard-coded film names. It derives tone curves, HSL adjustments, color grading, saturation, vibrance, grain, sharpening, noise reduction, and vignette settings. It is an approximation, not an encoded 3D LUT, and no fidelity percentage is established. |
| Exposure calibration | Implemented by `scripts/calibrate-luts.py`. It solves a per-LUT pre-gain by bisection using either midpoint or weighted neutral-ramp brightness. It handles top-level `.cube`, `.png`, and `.tif` files. |
| Installation and removal | Implemented by `scripts/install_ccprofiles.py`; `scripts/install-lr-ccprofiles.sh` wraps it on POSIX systems. `list` and `install --dry-run` show the plan first; an install that would overwrite a different same-named file **aborts unless `--force`**; overwritten files are backed up under `.filmsim-backup/<timestamp>/`; every install updates `.filmsim-manifest.json`; and `remove` deletes only files recorded in that manifest whose SHA-256 still matches. It does not install DCP base profiles. |
| Basic LUT QA | Implemented by `scripts/qa-luts.py`. It reports sampled midpoint, white, black, and contrast, and flags weak or inverted grayscale response. It does not test monotonicity, clipping, gamut range, or deviation from identity. |
| Contact sheets | Implemented by `scripts/try-looks.py`. It applies top-level `.cube` and `.png` LUTs to one Pillow-readable image, writes JPEG previews, and assembles a labeled JPEG sheet. |
| Source acquisition and curation | `scripts/fetch_sources.sh` lists or downloads selected upstream sources. `scripts/curate-rt-halclut.py` copies a named subset, or all PNGs, from a RawTherapee HaldCLUT tree. These workflows use upstream licenses and may use substantial disk and network bandwidth. |
| Spectral LUT baking | `scripts/bake-spectral-luts.py` drives the optional `spectral_film_lut` package for a built-in job list. This path is optional and not exercised by repository CI. |
| Fixtures, grader, and self-test | `evals/make_fixtures.py` creates deterministic synthetic fixtures. `evals/grade.py` grades separately produced evaluation artifacts and independently recomputes what it can, including re-deriving `decode_error_lsb` from the fixture LUT instead of trusting the declared value. `evals/test_safety.py` asserts the safety behaviour above; `evals/test_grader.py` asserts the grader still scores a known-good delivery full marks and still fails when artifacts are missing. `scripts/selftest.py` checks a synthetic calibration and Adobe table encode/decode path. These are internal checks, not application-host integration tests. |

## Requirements

The standalone Python tools require:

- Python 3.9 or newer
- `numpy>=1.21`
- `Pillow>=9.0`
- `tifffile>=2021.11.2`

Those versions are declared in [`requirements.txt`](requirements.txt). The repository has no lockfile, Python package metadata, or installed console entry point. Run scripts from the repository checkout.

Some workflows have extra requirements:

- Bash for `*.sh` wrappers. Native Windows users can use the Python entry points where one exists.
- `git`, `curl`, and `unzip` for the relevant branches of `scripts/fetch_sources.sh`.
- `uv` for the `spektra` fetch branch. The `spectra` branch can use `uv` or `venv` and `pip`.
- The separately installed `spectral_film_lut` package for `scripts/bake-spectral-luts.py`. Its current compatibility requirements are independent of this repository.
- An Agent Skills-compatible host if you want agent discovery. The Python utilities do not depend on an agent runtime.

Adobe creative profiles also depend on an Adobe host and a base camera profile that the host can resolve. The encoder defaults are:

| Encoder space | Adobe table metadata | Default base profile |
|---|---|---|
| `display` | `(1, 3, 0, 0.0, 1.0)` | `Adobe Standard` |
| `linear` | `(3, 1, 0, 1.0, 1.0)` | `Adobe Standard Linear` |

The scripts do not provide those DCP files. `Adobe Standard Linear` normally requires a separately acquired profile for the camera. Even `Adobe Standard` availability is a host and camera concern. An empty `crs:CameraModelRestriction` in generated XMP does not remove the base-profile requirement.

## Installation

### Use as an Agent Skill

Clone or copy the repository into a directory your agent host scans for skills, then follow that host's skill-installation instructions. The repository root contains [`SKILL.md`](SKILL.md), with supporting material under [`references/`](references/) and executable utilities under [`scripts/`](scripts/).

Cloning only makes the skill files available. Any command the skill runs still needs Python and the dependencies above, plus input LUTs and host-specific prerequisites.

```bash
git clone https://github.com/Macaron-Lawrence/film-sim-delivery.git
cd film-sim-delivery
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows, use the equivalent activation or interpreter path for the virtual environment.

### Use as standalone CLIs

Clone the repository, create an environment, install `requirements.txt`, and invoke scripts by path. There is no `film-sim-delivery` executable to install.

```bash
git clone https://github.com/Macaron-Lawrence/film-sim-delivery.git
cd film-sim-delivery
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/selftest.py
```

## Quick start with an arbitrary LUT library

The encoder contains a hard-coded `NAMES` mapping used for display names. For arbitrary filenames, `--allow-unknown` is required. Without it, recognized input files whose stems are absent from `NAMES` are silently skipped. If at least one supported input file was discovered, the command can report that it generated zero profiles and still exit successfully. Check the generated count and output directory.

The scripts only scan the specified directory itself, not subdirectories. This example uses an explicit working library:

```bash
export FILMSIM_ROOT=/absolute/path/to/film-work
mkdir -p "$FILMSIM_ROOT/luts"
# Copy your .cube or HaldCLUT .png/.tif files into $FILMSIM_ROOT/luts first.

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
  --allow-unknown
```

Use the same `--protect` value for calibration and profile generation. The encoder reads `pre_gain` from the calibration JSON, but it does not verify the JSON's recorded `mode` or `protect` values.

Inspect before installing. The installer aborts on a conflicting same-named file unless
you pass `--force`, and it backs up anything it overwrites, so never skip this step:

```bash
python3 scripts/install_ccprofiles.py list \
  --src "$FILMSIM_ROOT/lr-ccprofiles"

python3 scripts/install_ccprofiles.py install \
  --src "$FILMSIM_ROOT/lr-ccprofiles" \
  --dry-run
```

Then install to an explicit Adobe settings directory, or allow the installer to choose its platform-specific default:

```bash
python3 scripts/install_ccprofiles.py install \
  --src "$FILMSIM_ROOT/lr-ccprofiles"
```

Restart the Adobe host and test on representative raw files. The repository cannot establish host compatibility from the generated XMP alone.

## Task-oriented workflows

### Apply a LUT directly

`lr-filmsim.py` refuses to run unless you choose a destination: `--out DIR` writes new files,
and rewriting in place requires an explicit `--in-place` (which writes a timestamped backup
first). Pass `--calibration` so each LUT uses its own calibrated gain, plus the same
`--protect` you used for the profile, so both delivery paths share one tone contract.

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

Inspect a LUT without processing images:

```bash
python3 scripts/lr-filmsim.py \
  --lut "$FILMSIM_ROOT/luts/look.cube" \
  --info
```

For a linear-to-linear LUT, add `--linear-pipeline`. For a `.cube` with `LUT_1D_SIZE`, the parser applies the shaper before the 3D table.

The POSIX wrapper supports fuzzy LUT-name matching and one-level directory batches:

```bash
FILMSIM_ROOT=/absolute/path/to/film-work \
PRE_GAIN=1.0 \
bash scripts/apply-look.sh look \
  --out "$FILMSIM_ROOT/rendered" \
  --strength 0.75 \
  photos/
```

### Build a HaldCLUT

```bash
python3 scripts/cube-to-hald.py \
  --dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/hald" \
  --level 8 \
  --pre-gain 1.0
```

Level 8 produces a 512 by 512, 8-bit RGB PNG with 64 samples per channel. The script rejects levels whose per-channel grid exceeds 128. Install or select the resulting PNG using the target host's own CLUT settings.

### Generate approximate Lightroom presets

```bash
python3 scripts/lut-to-xmp.py \
  --dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/lr-presets" \
  --group "Film Simulation" \
  --pre-gain 1.0
```

Only filenames present in the script's `TASTE` table are processed. Unknown names are skipped because the script has no fallback grain and vignette recipe, and **producing zero files exits non-zero**. The output is a parameterized preset, not a general 3D-LUT conversion.

### Compare looks on one image

```bash
python3 scripts/try-looks.py photo.jpg \
  --lut-dir "$FILMSIM_ROOT/luts" \
  --out "$FILMSIM_ROOT/contact-sheets" \
  --only portra ektar \
  --size 1400 \
  --cols 3 \
  --pre-gain 1.0
```

This writes one JPEG per look and a file named `对比图.jpg`. The preview path converts the input to 8-bit RGB and does not preserve its metadata.

### Acquire and curate sources

List available helper branches before downloading anything:

```bash
bash scripts/fetch_sources.sh --list
```

The RawTherapee branch downloads and extracts a large archive:

```bash
FILMSIM_ROOT=/absolute/path/to/film-work \
SRC_DIR=/absolute/path/to/downloads \
bash scripts/fetch_sources.sh rt

python3 scripts/curate-rt-halclut.py \
  --src /absolute/path/to/downloads/HaldCLUT \
  --dst "$FILMSIM_ROOT/luts/rt"
```

Use `--list` on the curation command to count matched curated entries without copying. `--all` copies all PNGs it finds and derives output names from source paths. Review [`references/sources.md`](references/sources.md) and [`references/sourcing-playbook.md`](references/sourcing-playbook.md) before redistributing downloaded or derived files.

### Bake LUTs with `spectral_film_lut`

Run this with an interpreter where the optional package is already installed:

```bash
python3 scripts/bake-spectral-luts.py --list
python3 scripts/bake-spectral-luts.py \
  --out "$FILMSIM_ROOT/luts/spectral" \
  --size 33 \
  --only velvia trix
```

The script writes sRGB-input, Rec. 709-output `.cube` files through the upstream library. Its `--noise` flag is currently parsed but unused.

### Remove installed creative profiles

Removal uses the source directory as a filename manifest. It deletes same-named files from the destination and leaves every other file alone.

```bash
python3 scripts/install_ccprofiles.py remove \
  --src "$FILMSIM_ROOT/lr-ccprofiles"
```

If the source XMP files are no longer present, the installer has no record of what to remove.

## Script reference

| Entry point | Input and output | Key options | Side effects and validation |
|---|---|---|---|
| `scripts/lut-to-ccprofile.py` | Top-level `.cube`, `.png`, or `.tif` LUTs to profile XMP plus wrapper XMP | `--dir`, `--out`, `--only`, `--divisions`, `--space`, `--base-profile`, `--base-digest`, `--pre-gain`, `--calibration`, `--allow-unknown`, `--group`, `--protect` | Creates the output directory and overwrites same-named XMP files. Internally decodes each encoded table and requires less than one 16-bit LSB error. Does not test an Adobe host. |
| `scripts/calibrate-luts.py` | Top-level LUT files to JSON | `--mode`, `--protect`, `--merge`, `--out` | Writes JSON. Bisection assumes score is monotonic over gain 0.10 to 4.0 and does not check bracketing. `--merge` preserves unrelated existing records. |
| `scripts/lr-filmsim.py` | `.cube` or HaldCLUT plus images to processed images | `--out`, `--suffix`, `--strength`, `--linear-pipeline`, `--pre-gain`, `--info` | Default is destructive in-place replacement with no backup. Uses an atomic temporary-file replace. Argument ranges are not enforced. |
| `scripts/cube-to-hald.py` | Top-level `.cube` files to HaldCLUT PNG | `--level`, `--pre-gain`, `--only`, `--out` | Creates output directory and overwrites same-named PNGs. No round-trip comparison is performed. |
| `scripts/lut-to-xmp.py` | Known top-level `.cube` files to approximate preset XMP | `--group`, `--only`, `--pre-gain`, `--out` | Creates or overwrites XMP files. Unknown stems are skipped. No XML parse or Adobe-host test is performed. |
| `scripts/qa-luts.py` | Top-level `.cube` and `.png` LUTs to a console report | `--dir`, `--only` | Read-only. Samples a fixed grayscale probe and reports a binary heuristic based on black-to-white contrast and white level. |
| `scripts/try-looks.py` | One Pillow-readable image plus top-level `.cube` or `.png` LUTs to JPEG previews and a sheet | `--lut-dir`, `--only`, `--out`, `--size`, `--cols`, `--strength`, `--linear-pipeline`, `--pre-gain` | Creates output files and overwrites colliding names. This is visual-review material, not numeric QA. |
| `scripts/install_ccprofiles.py` | Source XMP directory to Adobe settings directory | `list`, `install`, `remove`, `--src`, `--dest`, `--dry-run`, `--force`, `--no-backup` | Install backs up anything it overwrites and updates the manifest; a conflicting same-named file aborts the run unless `--force`. Remove is manifest-exact and aborts if any recorded file has changed. DCP files are not changed. |
| `scripts/install-lr-ccprofiles.sh` | POSIX wrapper around the installer | `--list`, `--remove`; other arguments pass through after the first argument | Same side effects as the Python installer. Defaults to install. |
| `scripts/apply-look.sh` | Fuzzy LUT name plus files or directories to direct processing | `--ls`, `--out`, `--strength`, `--suffix`, `--linear-pipeline`, `--pre-gain`, `--flat` | May overwrite images because it delegates to `lr-filmsim.py`. Directory search is one level deep. Requires common POSIX tools. |
| `scripts/fetch_sources.sh` | Named upstream source to downloads or tool installation | `--list`, `rt`, `spectra`, `fuji`, `spektra` | Uses network access. May download hundreds of megabytes, extract with overwrite, create virtual environments, clone repositories, or install tools. |
| `scripts/curate-rt-halclut.py` | RawTherapee HaldCLUT tree to copied PNG subset | `--src`, `--dst`, `--all`, `--list` | Creates the destination even in `--list` mode and overwrites colliding copied files. It does not run LUT QA. |
| `scripts/bake-spectral-luts.py` | Built-in spectral film jobs to `.cube` files | `--out`, `--size`, `--only`, `--list`, `--noise` | Imports and executes third-party `spectral_film_lut`; writes in the output directory. `--noise` has no effect. |
| `scripts/verify-delivery.py` | A delivered profile (plus optional source LUT, calibration, real images) to `verification.json` | `--profile`, `--lut`, `--calibration`, `--pre-gain`, `--protect`, `--images`, `--declare`, `--out` | Read-only except for the output JSON. Every non-null check is computed here; items it cannot compute are listed under `unrecomputed` and are **not** treated as passing. Image-level metrics use the supplied source images as an additional floor, never a more lenient one. |
| `scripts/selftest.py` | Generated synthetic LUT to temporary calibration and XMP artifacts | `--work` | Without `--work`, removes its temporary directory after success. Checks table MD5 convention, encode/decode error, midpoint, and protected white. |
| `evals/test_safety.py` | Temporary workspaces to a pass/fail report | — | Asserts: no in-place write without `--in-place`, no silent overwrite, zero output exits non-zero, arbitrary filenames and XML-special characters work, install conflicts abort, rollback is manifest-exact, calibration mismatches are refused, and no document references a script that does not exist. |
| `evals/test_grader.py` | Builds a synthetic known-good candidate and grades it | — | Asserts the grader gives it full marks, still fails once artifacts are removed, and genuinely recomputes `decode_error_lsb`. |
| `scripts/selftest.sh` | POSIX wrapper for `scripts/selftest.py` | Arguments pass through | Same validation as the Python self-test. |
| `evals/make_fixtures.py` | Synthetic generator to committed-style fixture tree | `--out`, `--verify-reproducible` | Writes or overwrites fixtures. Checks defect signatures; reproducibility mode compares two generated trees. |
| `evals/grade.py` | An external evaluation run directory to console or JSON grading | `--eval`, `--fixtures`, `--no-fixtures`, `--json` | Read-only unless `--json` is given. Decodes candidate profiles and checks declared evaluation artifacts; it is not a general delivery verifier. |
| `evals/assemble_review.sh` | Evaluation run directories to a review directory and optional HTML | Optional workspace argument | Copies evaluation artifacts and may invoke an external skill-review generator. Uses `VIEWER` and `VIEWER_PY` when set. |

## How the conversion works

### LUT parsing and application

The shared implementation lives in `scripts/lr-filmsim.py`.

- The `.cube` parser reads `LUT_3D_SIZE`, optional `LUT_1D_SIZE`, and `DOMAIN_MIN` or `DOMAIN_MAX`.
- A complete 1D shaper is linearly interpolated before the 3D lookup. An incomplete shaper is ignored.
- The 3D lookup clips normalized coordinates to 0 through 1 and performs trilinear interpolation over eight neighboring samples.
- HaldCLUT dimensions are inferred from the square image's pixel count. Very large inferred grids are subsampled before use.
- `pre_gain` decodes sRGB values to linear light, multiplies them, and encodes them back before the LUT.
- `strength` linearly mixes the LUT result with the unmodified input block. The CLI does not clamp the supplied strength value.

### Calibration and highlight protection

`calibrate-luts.py` samples 19 neutral values. It bisects a gain range of 0.10 through 4.0 for 40 iterations. `midgray` targets the sampled value nearest 0.5; `brightness` targets a weighted average over the neutral ramp.

When `--protect` is greater than zero, calibration and Adobe table generation blend high-luminance LUT output back toward the input with a smoothstep transition. The threshold is not automatically selected. Pass the same value to both commands.

### Adobe RGBTable encoding

`lut-to-ccprofile.py` resamples the input LUT to a cubic table, quantizes each channel to 16 bits, and delta-encodes samples against a neutral ramp. It then serializes the table and its space metadata, compresses it with zlib, and encodes it with Adobe's custom base85 alphabet for an XMP attribute. The uppercase MD5 of the uncompressed table is used as the table ID.

For `display`, the sampled LUT receives display-encoded values. For `linear`, the encoder converts table inputs to sRGB before applying the source LUT and converts results back to linear. Space metadata and the named base profile must stay paired as shown in the requirements table.

The encoder emits one creative-profile XMP and one normal preset that references the profile UUID. These are generated files, not proof that an Adobe host accepted the profile.

## Configuration and environment variables

| Variable | Used by | Behavior |
|---|---|---|
| `FILMSIM_ROOT` | Most conversion, curation, fetch, wrapper, and installer scripts | Sets the working root. When unset, scripts use the current working directory. Several scripts look for `数据/luts` before `luts`. Explicit `--dir`, `--out`, `--src`, and `--dst` arguments are safer for reusable workflows. |
| `LR_SETTINGS_DIR` | `scripts/install_ccprofiles.py` | Overrides the Adobe CameraRaw `Settings` destination. |
| `XDG_CONFIG_HOME` | `scripts/install_ccprofiles.py` | On non-macOS, non-Windows systems, forms the default Adobe settings path. If unset, the script uses `~/.config`. |
| `APPDATA` | `scripts/install_ccprofiles.py` | On Windows, forms the default Adobe settings path. If unset, the script uses `~/AppData/Roaming`. |
| `SRC_DIR` | `scripts/fetch_sources.sh` | Overrides the source download and environment directory. If unset, the script uses `$FILMSIM_ROOT/sources`, or `$PWD/sources` when `FILMSIM_ROOT` is unset. |
| `PRE_GAIN` | `scripts/apply-look.sh` | Sets that wrapper's pre-gain. If unset, the wrapper uses `0.3472`. This is a wrapper default, not a universal value for arbitrary LUTs. |
| `VIEWER` | `evals/assemble_review.sh` | Explicit path to an external `generate_review.py`. If unset, the script probes three user-level skill locations. |
| `VIEWER_PY` | `evals/assemble_review.sh` | Preferred Python interpreter for the external viewer. It must be Python 3.10 or newer. |

Some default paths still retain the older `数据` layout. In particular, the default calibration output and curation source or destination are not consistently aligned with the newer `luts`, `sources`, and `lr-ccprofiles` layout. Use explicit paths in automation.

## Testing and verification

Run the local synthetic test:

```bash
python3 scripts/selftest.py
```

The self-test creates a synthetic 17-cube LUT, calibrates it, builds a display-space creative profile with highlight protection, decodes the embedded table, checks its MD5-derived ID and quantization error, and asserts midpoint and white response. It does not open Lightroom, Camera Raw, Photoshop, ART, RawTherapee, or Resolve.

The [CI workflow](.github/workflows/ci.yml) runs on Ubuntu, macOS, and Windows with Python 3.9 and 3.12. It:

1. installs `requirements.txt`;
2. parses every Python entry point with `ast`;
3. runs `scripts/selftest.py`;
4. regenerates synthetic fixtures and checks their defect signatures;
5. verifies that fixture generation is byte-reproducible;
6. runs `evals/test_safety.py` (no overwrite, no false success, no ghost scripts);
7. runs `evals/test_grader.py` (the grader still passes a known-good delivery and still fails without artifacts).

CI does not test third-party downloads, spectral baking, shell wrappers on native Windows, or integration with any photo or video host.

`evals/grade.py` is narrower than a full verifier. For its delivery evaluation, it independently decodes an embedded RGBTable, recomputes its MD5, reads metadata and base-profile fields, evaluates grayscale response, and checks wrapper UUID matching. It compares recomputed grayscale, midpoint, and white values with declarations where implemented. It accepts declared `decode_error_lsb`, brightness ratio, and image-level highlight metrics against thresholds; it does not independently recompute all of those metrics from source images. No production command automatically creates `verification.json`.

[`references/verification-schema.md`](references/verification-schema.md) describes the evaluation artifact expected by the grader. Treat it as a manual or external evaluation contract, not output promised by the encoder.

## Limitations and destructive operations

Read these before processing original files or installing profiles.

- `lr-filmsim.py` no longer overwrites by default: it requires `--out DIR` or an explicit `--in-place`, and an in-place write is preceded by a timestamped backup under `.filmsim-backups/`. `--overwrite` is required to replace an existing file in the output directory.
- The profile installer backs up anything it overwrites (under `.filmsim-backup/<timestamp>/`) and records every install in `.filmsim-manifest.json`; it aborts on a conflicting same-named file unless `--force` is given. Removal is manifest-exact: only files whose SHA-256 still matches what was installed are deleted, and a mismatch aborts the whole removal.
- TIFF writes do not preserve TIFF metadata. Pillow-based writes preserve an ICC profile when one was present, but do not preserve general EXIF or other image metadata.
- Image processing keeps only the first three channels. Alpha and extra channels are discarded. Grayscale input is expanded to RGB, processed, and reduced to the red channel rather than luminance.
- The image tools assume normalized RGB values and do not perform ICC color conversion. Results depend on the encoded values presented to them.
- Generated XMP interpolates filenames, labels, descriptions, and group names directly into XML. XML-sensitive characters such as `&`, `<`, or quotes are not escaped.
- `lut-to-ccprofile.py` processes any filename by default; `--only-known` restricts it to the built-in name table. Generating zero profiles exits non-zero, so a skip can no longer be mistaken for success.
- The profile's group follows `--group`, but the wrapper preset group is currently hard-coded to `胶片模拟 (光谱 LUT)`. Custom groups can therefore differ between the pair.
- Calibration JSON records `mode` and `protect`, but the encoder only consumes `pre_gain`; it does not enforce matching settings.
- `--base-profile` can name a custom profile, but `--base-digest` is only used when `--base-profile` is also supplied. The script does not verify either value against installed DCP files.
- `--protect`, `--strength`, `--pre-gain`, `--divisions`, and several size values lack complete range validation. Bad values can produce invalid output, extreme output, or runtime failures.
- HaldCLUT TIFF input is accepted by some core paths, while QA and contact-sheet discovery only include `.cube` and `.png`. Format coverage is not identical across scripts.
- `scripts/bake-spectral-luts.py --noise` is currently unused.
- The repository includes host guidance in [`references/hosts.md`](references/hosts.md), but that document is not a substitute for testing the exact host version, operating system, camera, and base profile you plan to ship.

## Safety and privacy

Normal LUT conversion, calibration, direct image processing, fixture generation, grading, and self-tests run locally. They do not upload images or call remote services.

`scripts/fetch_sources.sh` is different. Its `rt`, `fuji`, `spectra`, and `spektra` branches contact third-party services and may download archives, clone repositories, or install software. Review the script and upstream licenses first. The RawTherapee archive is described by the helper as roughly 402 MB before extraction.

## Repository layout

```text
README.md                 this file
README.zh.md              Chinese translation of this file
SKILL.md                  Agent Skill instructions
scripts/                  conversion, calibration, application, install, and source helpers
references/               format notes, host notes, source records, and evaluation schema
assets/                   example calibration JSON
evals/                    synthetic fixtures, fixture generator, grader, and review helper
.github/workflows/ci.yml  cross-platform synthetic CI
requirements.txt          minimum Python dependency versions
LICENSE                   repository code license
```

Further documentation:

- [`references/rgb-table-format.md`](references/rgb-table-format.md) explains the Adobe table layout.
- [`references/calibration.md`](references/calibration.md) discusses the intended calibration and highlight-protection model. Its §0 separates what CI can recompute from the figures that only early documents report; those carry the label **unarchived historical report, not covered by CI**.
- [`references/hosts.md`](references/hosts.md) records host assumptions and untested cases.
- [`references/sources.md`](references/sources.md) records upstream source and license notes.
- [`references/sourcing-playbook.md`](references/sourcing-playbook.md) gives a source-review workflow.
- [`references/pitfalls.md`](references/pitfalls.md) collects known failure modes. Some older claims in deeper documents may be stronger than current automated coverage; source code and this README define the implemented behavior. Where a deeper document quotes a number, check its provenance label first — figures CI cannot recompute are marked **unarchived historical report, not covered by CI**.

## License

Repository code and documentation are licensed under the [MIT License](LICENSE).

No third-party LUT collection is bundled. The repository does include the synthetic test LUT at [`evals/fixtures/luts/portra_like.cube`](evals/fixtures/luts/portra_like.cube) and generated synthetic bad-profile fixtures under [`evals/fixtures/bad/`](evals/fixtures/bad/). Files, datasets, profiles, archives, packages, and tools fetched from third parties retain their own licenses and terms. Check those terms before use or redistribution.
