# Changelog

All notable changes to `film-sim-delivery`.

## [Unreleased]

- **Provenance audit of the numeric claims.** An external review checked every figure in
  the docs against what the repository can actually demonstrate, and the results were
  applied:
  - **Fidelity percentages removed.** `SKILL.md`, `references/pitfalls.md` and
    `references/hosts.md` claimed the `lut-to-xmp.py` path keeps "~80 %" (or "75–85 %") of the
    look, while the README states no fidelity percentage is established. There was no
    definition, scoring formula, test LUT, test image, script or benchmark behind the
    number, so all of them were replaced by: parameterised approximation, not an encoded
    3D LUT; no reproducible fidelity-scoring method exists, so no percentage is given.
    (`scripts/lut-to-ccprofile.py` and `scripts/lut-to-xmp.py` no longer say "100 %" either.)
  - **Unarchived numbers now labelled as such.** `references/calibration.md` gained a §0
    "provenance and evidence status" section that separates what CI can recompute from what
    only early documents report. The label is **unarchived historical report, not covered by
    CI** — deliberately not "historical measurement", which would still assert the tests
    happened and were sound. Covers the 6-RAW aggregate (0.986 / 247 / 3.31 % / 5.06), the
    0.40–1.67 pre-gain span, and the 209 white-point figure.
  - **What CI does prove, stated explicitly:** on a synthetic fixture, unprotected white
    output is in 0–220 (`evals/make_fixtures.py`) and the bad sample is ≤ 215
    (`evals/grade.py`). That is a synthetic phenomenon, not a value for real LUTs.
  - **Arithmetic error found while auditing.** `calibration.md` §2 claimed inputs
    200/220/240/255 map to 198/214/237/255 with `--protect 0.68`. Recomputing with the
    documented formula and that section's own unprotected table gives **194.0/212.5/237.0/255.0**
    — 240 and 255 match, 200 and 220 are off by 4.0 and 1.5 and cannot be reproduced from
    the document itself. The recomputed values are now shown and the discrepancy is noted.
  - **`top5pct_median` definition pinned.** Field name means median; some prose said mean.
    Documentation now states the median, and `verification-schema.md` records that the grader
    evaluates `brightness_ratio`, `top5pct_median`, `pct_ge_250` and `highlight_detail_std`
    against declared values without recomputing them from source images.
  - `references/verification-schema.md` marks its example numbers as placeholders, because
    those same values had been reused as if they were measurements.

- **README rewritten** to describe what the code actually does: a per-workflow
  status table that names what is *not* verified, explicit dependency and
  base-profile requirements, a full script reference with side effects, and
  limitations/destructive-operation warnings. Claims in the earlier version that
  were stronger than the automated coverage (fidelity percentages, the highlight
  cap, benchmark scores) are gone from the README; source code and the README now
  define implemented behaviour.
- **Added [`README.zh.md`](README.zh.md)** — a complete Chinese translation of the
  README, linked from the top of both files. Same structure, same tables, same
  caveats; only the prose is translated, so commands and paths stay identical.
- **Removed `references/README.en.md`.** It was an English quick start written
  before the root README existed, and it had become a second, weaker source of
  truth: it still asserted the highlight-cap figure and per-LUT gain range that
  the rewritten README no longer claims, and it duplicated the README's structure
  without being maintained alongside it. The root [`README.md`](README.md) is now
  the complete English reference; `SKILL.md` points there (`references/` is down
  to 7 files).
- Verified from a clean state over HTTPS: clone → `python3 -m venv` →
  `pip install -r requirements.txt` → `scripts/selftest.py` passes, and
  `evals/make_fixtures.py --verify-reproducible` yields the same tree hash as CI
  (`a83a297b51f8cee3`) on Python 3.9.6 and 3.13.15 alike.

## [0.3.1]

- **Windows fix.** Every Python entry point died with
  `UnicodeEncodeError: 'charmap' codec can't encode character` whenever stdout was
  redirected — CI captures output as a pipe, so a Windows console falls back to
  cp1252 and cannot encode `✓` or the Chinese status text. Each script now pins
  `sys.stdout` / `sys.stderr` to UTF-8 at import time (guarded, no-op elsewhere),
  and CI sets `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` as a second layer.
  Reproduction: `PYTHONIOENCODING=cp1252 python3 scripts/selftest.py` — exited 1
  before, exits 0 now.
- **Fixtures are byte-reproducible.** `evals/make_fixtures.py` no longer uses
  `uuid4()` for profile IDs (derived from the table ID instead), so regenerating
  produces identical bytes. Added `--verify-reproducible`, which generates twice
  into temp dirs and compares tree hashes; CI runs it on all three platforms.
- **Python 3.9 fix.** `evals/make_fixtures.py` called
  `Path.write_text(..., newline="\n")`, a keyword that only exists from 3.10, so
  every 3.9 cell failed with `TypeError: write_text() got an unexpected keyword
  argument 'newline'`. Replaced by a `write_lf()` helper. The main pipeline was
  unaffected — `selftest.py` already passed on 3.9.
- **CI matrix** covers Ubuntu / macOS / Windows × Python 3.9 / 3.12, all six green.
- `LICENSE` is plain MIT text again so GitHub detects the licence (a trailing
  provenance note had made it report `NOASSERTION`); that note lives in the
  README's Licence section.

## [0.3.0] — first public release

Initial open-source release of the skill. Pipeline: `LUT → calibration → target
format → install → verification`.

### Delivered
- **15 scripts** — `lut-to-ccprofile.py` (main Adobe creative-profile encoder:
  custom base85 + zlib + delta-encoded RGBTable), `calibrate-luts.py` (per-LUT
  exposure bisection), `install_ccprofiles.py` (macOS/Windows/Linux),
  `lr-filmsim.py`, `cube-to-hald.py`, `lut-to-xmp.py`, `qa-luts.py`,
  `selftest.py`, `bake-spectral-luts.py`, `curate-rt-halclut.py`,
  `fetch_sources.sh`, `try-looks.py`, `apply-look.sh`, `cube-to-hald.py`,
  `install-lr-ccprofiles.sh`.
- **8 references** — RGBTable binary format spec, 7 hard pitfalls, calibration
  method, verification schema, host/OS/camera matrix, LUT sourcing playbook and
  source list, English quick start.
- **`SKILL.md`** — 3 hard rules, decision tree, main path, branches, diagnosis
  table, sourcing, verification requirement, script index, cross-platform and
  coverage notes.

### Verified behaviour (measured, not asserted)
- `crs:RGBTable` value is the MD5 of the *decompressed* table — confirmed
  against a Fujifilm `Velvia.xmp` and an Adobe-shipped camera profile.
- Space ↔ metadata ↔ base-profile pairing corrected: `display` → `Adobe Standard`
  + `(1,3,0,0.0,1.0)`; `linear` → `Adobe Standard Linear` + `(3,1,0,1.0,1.0)`.
  A mismatch double-applies gamma and is the #1 cause of "everything is grey".
- Highlight protection: `--protect 0.68` blends high lights back toward the input.
  (The 0.3.0 release note also carried an aggregate metric set — 0.986 / 247.1 /
  3.31 % / 5.06 — reported from 6 unidentified RAW files. The RAW files, hashes,
  parameters, software environment, measurement script and result files were never
  archived, and CI does not recompute these values; see `references/calibration.md` §0.)
- Per-LUT calibration is mandatory. (The 0.3.0 release note also cited a
  0.40–1.67 pre-gain span; that set of LUTs was never archived with the repository,
  so it is recorded here as an unarchived historical report, not a reproducible
  measurement — see `references/calibration.md` §0.)

### Evals
- 3 artifact-graded tasks (deliver / diagnose space mismatch / diagnose missing
  highlight protection) with synthetic fixtures and an independent decoder that
  re-derives every declared number.
- Results: task C **9/9** with-skill vs **4/10** baseline; task B **5/5** vs 4/5;
  trigger accuracy 19/20 → after the description fix, 5/5 on a regression
  spot-check (recall 10/10).

### Fixed during development
- Base85 digit order and trailing-group byte count (the partial group emits
  `n-1` bytes, which is easy to get wrong and silently corrupts the table).
- `unbound variable` in bash wrappers when `$VAR` is followed by CJK punctuation
  → `${VAR}` everywhere.
- Missing `from pathlib import Path` in two scripts (Python 3.9 breakage),
  caught by the eval; a full import check was added.
- Grader: exact-string root-cause matching replaced by semantic matching;
  undecodable candidate tables now record `0` with a reason instead of crashing.
- Eval review tooling requires Python ≥ 3.10; the assembler now selects an
  interpreter automatically.

### Not covered (deliberately)
- `.dcp` camera-matching problems (that is camera calibration, not film delivery).
- Video colour grading and video LUTs.
- Generic post-processing (grain, vignette, cut-out, format conversion).
