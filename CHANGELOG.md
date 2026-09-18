# Changelog

All notable changes to `film-sim-delivery`.

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
- Highlight protection: `--protect 0.68` restores brightness ratio 0.915 → 0.986,
  top-5 % 207.6 → 247.1, pixels ≥ 250 from 0 % → 3.31 %, highlight-detail std
  1.02 → 5.06 (untreated original: 1.000 / 248.1 / 4.27 % / 6.10).
- Per-LUT calibration is mandatory: required gain spans 0.40–1.67 across sources.

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
