# Changelog

All notable changes to `film-sim-delivery`.

## [0.4.0] — 2026-09-19   *breaking: CLI defaults changed*

> **升级前请读**：`lr-filmsim.py` 不再默认原地覆盖，必须给 `--out` 或显式 `--in-place`；
> 安装器遇到同名冲突会中止（需 `--force`），并写备份与 manifest；三个生成器零产物时返回非零退出码。
> 依赖旧行为（不带参数就覆盖）的脚本需要改。

### Safety defaults (breaking CLI changes)

An external review found that the shipped CLI could destroy user data and that the
skill's own instructions did not reflect what the code did. Every item below was
reproduced before being fixed, and `evals/test_safety.py` now asserts it in CI.

- **`lr-filmsim.py` no longer overwrites by default.** Previously, omitting `--out`
  silently rewrote the input file in place with no backup (reproduced: source JPEG
  hash changed, zero backups). It now refuses to run without `--out DIR` or an
  explicit `--in-place`; `--in-place` writes a timestamped backup under
  `.filmsim-backups/`; an existing output file requires `--overwrite`.
- **`lr-filmsim.py` reuses the calibration chain.** `--calibration` looks up the
  per-LUT `pre_gain` by name (it previously had no knowledge of calibration at all —
  the string did not appear in the file), and `--protect` applies the same
  highlight-protection blend as `build_table()`, so both delivery paths now share one
  tone contract.
- **Installer has a real lifecycle.** `install_ccprofiles.py` gained: a printed plan,
  conflict detection that **aborts** (reproduced: a user's own same-named file was
  overwritten with no backup), backups under `.filmsim-backup/<timestamp>/`, a
  `.filmsim-manifest.json` recording name/SHA-256/source/time, and a manifest-exact
  `remove` that skips — and aborts on — files that changed since install.
- **Zero output is a failure.** `lut-to-ccprofile.py`, `lut-to-xmp.py` and
  `cube-to-hald.py` now exit non-zero when they produce nothing (reproduced: three
  client-style filenames produced "0 profiles" with exit code 0, which an agent reads
  as success).
- **Any filename is processed by default.** `--allow-unknown` is gone from the happy
  path (`--only-known` is the opt-in restriction). Client names no longer vanish.
- **XML correctness.** Names with `&`, `<`, `>` and quotes are escaped and every
  written XMP is re-parsed; failing files are deleted rather than left as half-written
  trapdoors. Reproduced before the fix: 4 of 6 generated files failed standard XML
  parsing. While implementing this, escaping the apostrophe broke the payload — the
  Adobe base85 alphabet contains `'` — so attribute escaping only touches `&`, `<`,
  `"`, and an assertion now rejects XML-special characters in table data.
- **Calibration parameters are enforced.** The generator refuses to run when the
  calibration JSON's `mode`/`protect` disagree with the current invocation
  (reproduced: `--protect 0.68` with a `protect=0.0` calibration silently produced a
  delivery that did not match what was calibrated).

### Verification loop

- **New `scripts/verify-delivery.py` produces `verification.json` for real.** The repo
  previously contained no production code that wrote it — the schema was just an
  expectation. It recomputes table-ID/MD5, metadata↔base pairing, the gray-scale
  response, mid-grey and white from the delivered table; `decode_error_lsb` when given
  the source LUT and calibration; and brightness ratio, top-5 % median, ≥250 share and
  highlight-detail std when given real images. Anything it cannot compute is listed as
  `unrecomputed` and is **not** treated as passing.
- **Image-level thresholds are now relative to the supplied images.** The absolute
  targets came from the unarchived numbers in §0; run on a real image whose highlights
  are shallower, they are simply unreachable. The verifier uses the source image as an
  additional floor and never a more lenient one, and records exactly which floor it
  applied in `thresholds_used`.
- **The grader recomputes instead of trusting.** `evals/grade.py` now re-derives
  `decode_error_lsb` by rebuilding the table from the fixture LUT using the declared
  parameters, and refuses to count declared image-level metrics as evidence unless real
  images are present. Its bad-fixture bound was also aligned with the fixture
  generator's own signature (215 → 220; the generator asserts 0–220, so the grader was
  strictly harsher than the sample it was grading).
- New `evals/test_safety.py` (21 assertions) and `evals/test_grader.py`, both wired
  into CI.

### Documentation

- **`SKILL.md` rewritten around execution constraints.** Phantom scripts removed:
  `setup-art-bridge.sh`, `make-art-profiles.py` and `make-lr-external-editor-app.sh`
  were referenced as available but do not exist in this repository; the ART and
  external-editor flows now say plainly that they must be configured by hand and are
  not shipped. The hard constraints (no default overwrite, install dry-run first, zero
  output = failure, arbitrary filenames, XML limits, calibration must match, verify for
  real) are now §0 at the top; catalogue/coverage material moved down. Every command is
  written against an absolute `$SKILL_ROOT`, never the current directory.
- `README.md` / `README.zh.md` updated to describe the new defaults, the new scripts,
  and the additional CI steps. Both were checked for links, code fences and section
  parity.
- Trigger queries extended with the exclusions the description promises (video LUTs,
  `.dcp` camera matching, ordinary develop presets, video grading, cut-outs).

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
    output is in 0–220 (`evals/make_fixtures.py`) and the bad sample is ≤ 220
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

## [0.6.0] — 2026-09-22   *feature: look strength*

Asked whether LUT strength could be dialled back, and whether baking a 50 % LUT per
strength into separate preset folders was the right way to do it. It works, but it is
the expensive option, and the cheap one was already half-present in the output.

What the audit found: our wrapper presets are structurally identical to Adobe's and
Fujifilm's shipped ones — including `crs:Amount="1"`, the field that carries how
strongly a Look is applied. The strength mechanism was already in our files, pinned
at 100 %, and the preset-level `SupportsAmount2` was set to `False` exactly as the
official profiles set it.

Three ways to control strength, all now implemented and tested:

- `--bake-strength s` bakes the intensity into the table:
  `out = s·LUT + (1−s)·input`, in the look's own space. Verifiable, frozen after the
  fact, one full table per strength.
- `--amounts 1,0.75,0.5,0.25` emits extra wrapper presets that share the **same**
  embedded table and the same Look UUID, differing only in `crs:Amount`. This is the
  "50 % preset folder" idea at ~1.7 KB per preset instead of a duplicated 76 KB table
  per strength, and it is the structure Adobe/Fujifilm already use.
- `--supports-amount` sets `SupportsAmount`/`SupportsAmount2` to `True` on the preset,
  which is the documented way to make a host offer a strength slider (they are the
  flags for Lightroom's Amount control; `SupportsAmount` was superseded by
  `SupportsAmount2` from Camera Raw 1.4). Adobe's own profiles ship `False`, and no
  host was available to confirm the slider appears, so this is opt-in and labelled as
  unverified rather than presented as working.

`lr-filmsim.py --strength` already existed for the direct path and uses the same
blend, so `--bake-strength 0.5` and `--strength 0.5` agree.

New `evals/test_strength.py` (13 assertions, in CI) locks this down: baked strength
must equal `s·LUT + (1−s)·input` within 1 LSB, must actually differ from 100 %,
must keep white at 255, the multi-amount presets must share one table and one UUID,
`--supports-amount` must flip only the preset-level flags, and the direct-path
`--strength` must match the baked math.

## [0.5.0] — 2026-09-22   *breaking: install rollback, verdict semantics, and a `--mode` contract*

Follow-up to an external review of 0.4.1. Five issues, all reproduced first.

### Install / rollback (P0)

`remove` only deleted the files it had installed; it never put back the file it had
overwritten. So "rollback" meant "undo the install", not "restore the previous
state" — anyone reading "manifest-exact rollback" would reasonably expect their own
profile to come back.

`remove` now rolls back to the pre-install state: files that were overwritten are
**restored from their backup** after checking the recorded hash, files that were
newly added are deleted, and if any recorded file was modified after installing (or
its backup is missing) the whole removal aborts rather than leaving a half-finished
state. `--dry-run` prints which files will be restored and which will be deleted.

### Verification verdict (P0)

`verify-delivery.py` could print `verdict: pass` while image-level metrics were never
computed — exactly the "not recomputed is not a pass" rule it was built to enforce.

The verdict is now three-valued and the exit code follows it:

| verdict | meaning | exit |
|---|---|---|
| `pass` | everything required was recomputed and passed | 0 |
| `partial` | computed checks passed, some metrics lacked input (**not a pass**) | 3 |
| `fail` | a check failed, or the run required images (`--require-images`) and got none | 1 |

`--allow-partial` is the only way to make `partial` exit zero.

### Grade thresholds (P1, and a documentation contradiction)

The docs said the source-image baseline was "never more lenient" than the absolute
target; the code used `min(absolute, fraction × source)`, which *is* more lenient
whenever the source meets the absolute target. The intent is now decided and both
sides say the same thing: **two-stage** — if the supplied images meet the absolute
target, the absolute target applies (stricter); only when they do not does the
retention floor apply. Either way the output may not be worse than the input, and
which branch was used is recorded in `thresholds_used.basis`.

### Calibration `mode` contract (P1)

0.4.0 enforced `protect` but not `mode`: generation never had to declare which mode
its calibration was produced with, so half the contract was unenforceable. Using
`--calibration` now requires an explicit `--mode`, which must match the recorded
mode; a mismatch aborts. This immediately broke three of our own call sites
(`selftest.py`, `test_safety.py`, `test_grader.py`) — which is what a contract
actually taking effect looks like.

### Range validation (P1)

`--divisions` (1–64), `--protect` (0 ≤ p < 1), `--pre-gain` (0.01–8.0) and
`--strength` (0–1) are now rejected at the entry point instead of producing invalid
or extreme output. Size values in the preview helpers and `cube-to-hald.py --level`
remain unchecked.

### Glob injection in failure cleanup (found while auditing)

The generator's cleanup after a failed encode used `glob("*{stem}*.xmp")`, so a stem
containing `*`, `?` or `[ ]` widened the pattern: with `stem="*"` it matched and
deleted *other* deliveries in the output directory (reproduced). Cleanup now unlinks
only the two exact paths it just wrote.

### Evals now test behaviour, not just artifacts

- `eval 0`/`eval 2` asked for image-level metrics while shipping no image, which left
  a candidate three bad options: invent numbers, copy the example, or fail. The
  fixtures now include a deterministic test photo, and **the grader recomputes the
  four image-level metrics itself** from that photo; declared values are only
  cross-checked. A declared value that disagrees with the recomputation fails.
- Two new safety-behaviour tasks: `eval 3` (a user demanding in-place replacement
  with no backup) and `eval 4` (a user demanding an unconfirmed overwrite of their
  own profile). Both are graded from filesystem consequences — original hashes,
  backups, manifest — not from what the agent says it did. Verified to discriminate:
  the unsafe behaviours score 2/4 and 0/4, the safe ones 4/4.
- `test_safety.py` grew from 22 to 34 assertions: SKILL.md must still contain every
  execution gate, no SKILL.md command may rely on the current working directory, the
  README may not regress to any of the previously-corrected claims, `remove` must
  actually restore, and a missing backup must abort.

The test photo is deliberately built so the metric can discriminate rather than
produce knife-edge noise: most ≥250 pixels are genuinely near-white, because
protect=0.68 pushes inputs below ~250.6 under 250 — a fixture that spreads a linear
ramp across the highlight range would lose ~23 % of its ≥250 share for reasons that
have nothing to do with delivery quality.

## [0.4.1] — 2026-09-19

Follow-up cleanup: the 0.4.0 round fixed the scripts and `SKILL.md`, but several
documents kept describing the old behaviour. Every item below was a direct
contradiction with the code or with another part of the same document.

- `references/calibration.md` §0 said the repo had no code to recompute the
  image-level metrics. That stopped being true when `verify-delivery.py --images`
  landed, so the paragraph now says both things at once: the metrics **can** be
  recomputed from images you supply, while the six RAW files behind the historical
  aggregate were never archived, so **that** older result still cannot be
  reproduced — a fresh `--images` run measures your images, it does not re-check
  the old numbers.
- The READMEs claimed "no production command automatically creates
  `verification.json`". Replaced with what the verifier actually does, including the
  part that matters: without `--images` it does not compute the image-level metrics
  at all, so an example value must never be presented as this delivery's measurement.
- README statements that contradicted the shipped code were all corrected, not just
  the ones reported: `--allow-unknown` was still documented as required for arbitrary
  filenames (it is the default now), `lr-filmsim.py` was still described as
  overwriting in place by default, `lut-to-xmp.py` as doing no XML validation,
  generated XMP as not escaping special characters, the encoder as not enforcing
  calibration `mode`/`protect`, and the wrapper preset group as hard-coded. The one
  remaining limitation was reworded so it is visibly still true (numeric range
  validation is not complete) rather than reading as a stale claim.
- `scripts/calibrate-luts.py` and `references/pitfalls.md` quoted per-source
  calibration figures as plain facts. They now say those came from early documents
  that were never archived, must not be reused, and that the current input has to be
  measured — which is what the script exists to do.
- `references/verification-schema.md`'s example block **was** the historical number
  set (0.977 / 247.1 / 3.31 / 5.06), which is how those values came to be quoted as
  measurements in the first place. The example now uses neutral placeholder values,
  with a note directly above it, so the path that caused the confusion is closed
  rather than just annotated.

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
