# CLAUDE.md — mkv-subtitle-tagger

Tags untagged (`und`) subtitle tracks in `.mkv` files with their real language, learned from a
correctly tagged reference file or, without one, from built-in language profiles. Python (standard
library only) + MKVToolNix; runs on Windows, macOS and Linux. **Usage, options, `config.json`, output
files, how it works and the pitfalls are in [README.md](README.md). It's the single source, so don't
restate it here.**

## Using it on a video folder (the usual request)

1. **Dry run first, always**: `python -I -X utf8 '<this repo>/fix_subs.py' '<folder or .mkv>'`
   (or the `fix-subs.cmd` / `fix-subs` launcher). Any shell works.
2. **Read the simulation and `report.txt`**, not just the summary line:
   - every `REVIEW` line and its `why:` line
   - every `variants … SWAPPED` decision
   - each variant pair against the track order (README § Pitfalls)
   - without a reference: every `built-in` naming note (SDH, variants, confirmed pairs)
   - every `SUSPECT` line (a tag the text contradicts) and every `renamed` junk name
3. **Apply only when the review is clean** and the user asked for the files to be fixed:
   `… --apply` reuses the dry run's plan.
   - Anything flagged: show it to the user and don't apply.
   - If the user confirms a fix: edit `plan.json` (set `"confident": true` on the checked entries),
     then apply.
   - **Suspect tags:** Claude's shell has no terminal, so `--apply` keeps them all. List them for the
     user, then set `"replace": true` on the entries they accept. Pass `--replace-suspects` only when
     the user says to replace them all.
4. **Report** the files changed and the tracks verified. The apply step re-reads every file itself.

## Conventions

- **Python uses the standard library only**, with type hints, and supports **3.9+** (no `match`, no
  `X | Y` type unions).
  - **Always run as `python -I -X utf8`:** isolated mode because the subtitle text comes from outside,
    and UTF-8 output.
  - **`-I` drops the script's own folder from `sys.path`**, so every entry script inserts it first
    (`fix_subs.py`, `apply_plan.py`, `build_profiles.py`).
- **Indentation and line endings follow `.editorconfig`:** 2 spaces, Python 4, LF, `.cmd` CRLF.
  `.gitattributes` holds git to the same line endings, whatever each machine's `core.autocrlf`.
- **Every MKVToolNix call goes through `run_tool()` / `get_mkv_info()`** (`mkv_common.py`), which pass
  `--output-charset UTF-8` and decode as UTF-8. Non-ASCII track names must survive a write + verify.
- **Paths are made absolute with `os.path.abspath`, never `realpath`/`resolve()`:** on Windows those
  turn a mapped network drive into a UNC path, so plan keys and work-folder names would change.
- **Tool locations come only from `config.json`** via `load_config()` + `find_mkvtoolnix()`.
  - **The shipped file** holds the standard install folder per OS (`windows` / `macos` / `linux`).
  - **A configured folder without the programs** prints a warning, then falls back to `PATH` and the
    standard folders; an explicit `--mkvtoolnix-dir` stops the run instead.
  - The only other tool paths are the fallback list in `standard_mkvtoolnix_dirs()`.
- **`config.json` is not a credentials file:** it holds only paths and numbers, so reading it is fine.
  It must **never hold secrets**.
- **Errors are never swallowed:**
  - **Expected failures** raise `TaggerError`; the entry points print them and exit with its
    `exit_code`.
  - **Unexpected ones** propagate with their traceback.
  - **Exit codes:** `fix_subs.py` and `apply_plan.py` use 0 = done, 1 = error, 3 = needs review /
    apply refused.
- **This repo is public on GitHub:**
  - no internal hostnames or personal paths in committed files
  - no film or series names, no release names; test text is written for the tests
    (`tests/samples.py`)
  - **License:** MIT for the code, CC BY 2.0 FR for `profiles.json` (README § License). Any new data
    source needs a license that allows redistribution, and a credit there.

## Testing a change

- **Automated:** `python -I -X utf8 -m unittest discover -s tests` (unit tests + end-to-end tests on
  generated `.mkv` files; the latter skip themselves without MKVToolNix). Run it after every change.
- **Regression by hand**, after any change to matching:
  - Take a season that was already fixed and run with an explicit `--reference`, every fixed file as
    `--target`, and `--retag-all` (without it, already tagged tracks are skipped, so nothing would be
    compared).
  - The dry run must end with `0 of N subtitle tracks … would change; 0 need review`.
  - `--apply` right after must print "Reusing the plan" and write nothing.
- **Built-in profiles**, after rebuilding `profiles.json` or changing the thresholds: run without a
  reference on files whose truth is known, and check that no track is confident but wrong.

## Design decisions

- **Reference-based n-grams, not a language-ID library:** no dependencies, and the reference supplies
  the exact labels the series uses (variants, SDH, naming).
- **One-to-one greedy assignment per file**, so close languages (Danish/Norwegian) can't collide.
- **Variant tie-break by reference-unique lines:** n-gram scores can't separate near-identical variants
  (fr-CA/fr-FR differed by a single title card).
- **Tracks are addressed by UID**, not position. Plan entries record the UID, and apply checks it.
- **"Untagged" means no tag a player can rely on** (`untagged_track_ids()`): language `und`, BCP 47
  `und`, or no language element at all. mkvmerge reports the last as the default `eng`, and it's told
  apart only when the file's other tracks carry BCP 47 tags. MKVToolNix v103 itself omits the legacy
  element for English, so "eng without BCP 47" is no proof of a missing tag in older files.
- **Already tagged tracks keep their language.** They still claim their label, so it isn't given to a
  second track. An exact tag is authoritative and no variant swap moves it.
  - **A junk name** ("SubRip", "Track 3": `is_junk_name()`) is replaced, because players show the name
    instead of the language. It's also left out of reference and pool labels.
  - **Suspect tags** are tags the built-in profiles are sure the text contradicts:
    - **Found before the assignment**, so a wrong tag can't claim another track's label, then
      identified like untagged tracks.
    - **Written only with the user's yes** (prompt, `"replace": true`, or `--replace-suspects` for
      confident suggestions). They never block `--apply`.
    - **Code aliases** (`fra`/`fre`, `nob`/`nor`) are the same language (`same_language()`).
  - **`--retag-all`** re-identifies and rewrites tagged tracks without asking.
- **Fully tagged files aren't read unless `--check-tags`:** each file is read end to end, which costs
  time on a NAS. The tags of the files that are read (targets and reference) are always checked.
- **The reference file is never a target.** Its own untagged tracks stay as they are, and the run says
  so. Its tags are still checked: a suspect one isn't learned from, and a junk name is removed.
- **The dry-run plan is reused on `--apply` when the size + modified-time fingerprint and the
  plan-changing options match.** `mkvpropedit` changes the modified time, so a file that was written
  invalidates the old plan.
- **Built-in profiles** (`profiles.json`, built by `build_profiles.py` from Tatoeba, CC BY 2.0 FR,
  credited in the README):
  - **Matched on letter n-grams only** (`content_profile()`). With spacing grams, sentence-vs-subtitle
    formatting made every Chinese and Japanese track look Korean.
  - **Confidence is the lead over the best other language.** The thresholds were measured on a real
    44-language subtitle set and on held-out Tatoeba text: the wrong answers had leads of 0.003 or
    less. Close pairs in one file confirm each other.
  - **Variant marker words only count as contrast between siblings.** A lone fr-CA track that was the
    France text leaned fr-FR and got named wrong.
- **With a reference, the built-in profiles only flag, never relabel silently.** A track whose language
  they're sure the reference got wrong is marked `REVIEW` with their suggestion. The usual cause is a
  language missing from the reference, whose track gets the closest leftover label.
- **Image-based subtitle tracks (PGS, VobSub)** aren't extracted or counted as untagged: there's no text
  to read.
- **Not done yet (ideas):**
  - writing regional BCP 47 tags (`fr-CA`) on MKVToolNix ≥ v51, instead of `fre` + a name
  - telling Cantonese from Traditional Chinese without a reference (subtitles are usually written
    standard Chinese)
  - audio track languages
  - OCR for image-based subtitles
