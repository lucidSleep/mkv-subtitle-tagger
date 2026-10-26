# mkv-subtitle-tagger

**Detects the language of untagged subtitle tracks in `.mkv` (Matroska) files and tags them**, so
players such as VLC, Plex, Jellyfin or Kodi show **"French (Canada)"** instead of **"SubRip"**,
"Unknown" or "Track 7". A command-line tool in Python, built on
[MKVToolNix](https://mkvtoolnix.download/).

Many `.mkv` files carry dozens of subtitle tracks with **the language set to `und`** (undetermined)
and no name. This tool works out each track's language **from its text**:

- **with a reference**: a correctly tagged `.mkv` with the same subtitle set (another episode of the
  same series, for instance), whose exact labels it copies: "SDH", "Spanish (Latin America)", …
- **without one**: with its **built-in language profiles** (about 60 languages).

It then writes the tags **in place** with `mkvpropedit`: a header edit, no remux, seconds per file.

**Tracks that already have a language keep it.** Two exceptions:
- **Junk names:** a name like "SubRip" or "Track 3" (which players show instead of the language) is
  fixed.
- **Contradicted tags:** a tag the text contradicts ("tagged English, the text is Polish") is
  reported, and `--apply` asks before replacing it.

Runs on **Windows, macOS and Linux**.

## Requirements

- **Python 3.9 or newer**. It uses the standard library only, so there's nothing to `pip install`.
  It's preinstalled on most Linux systems. On Windows and macOS, get it from
  [python.org](https://www.python.org/downloads/).
- **[MKVToolNix](https://mkvtoolnix.download/)**, tested with v46 and v103. Its standard install
  folder is preset in [`config.json`](#configuration-configjson) for each OS. If it's elsewhere, it's
  found on `PATH`.

**Installing:** download this repository (**Code → Download ZIP**) and unzip it anywhere. There's
nothing else to set up.

## Usage

```text
Windows        fix-subs "D:\Videos\Some Series\Season 1"
macOS, Linux   ./fix-subs ~/Videos/"Some Series"/"Season 1"
any OS         python3 fix_subs.py <folder or .mkv>         (python on Windows)
```

1. **Dry run** (the default): it scans the folder, prints what it found and the role of each file, then
   **simulates the result** for every track. **Nothing is written.**
2. **Check** the simulation, and the report for any track marked `REVIEW`.
3. **Apply**: run the same command with `--apply`. If the files haven't changed since the dry run,
   **the dry run's plan is reused as is**, including any hand edits to `plan.json`. Every written file
   is re-read to verify.
   - **Suspect tags:** before anything is written, it asks about each one: `Replace the tag? [y/N/a]`.
     `a` = yes to all the remaining ones. `--replace-suspects` answers yes to all of them up front.

Pass **a single `.mkv`** instead of a folder to fix just that file. The other files in its folder are
still scanned for a reference.

- **Launchers:** `fix-subs.cmd` (Windows) and `fix-subs` (macOS / Linux) run `fix_subs.py` with the
  right Python flags. Call them by full path, or add this folder to `PATH`.
- **"Permission denied"** on macOS / Linux: run `chmod +x fix-subs` once, or use `sh fix-subs …`.
- **Windows only:** don't end a quoted folder path with a backslash (`"D:\Videos\"`). cmd.exe turns
  `\"` into a literal quote; the tool detects this and stops with a clear message.

### Sample output (dry run, with a reference)

```text
Role        Subs Untagged  Name
TARGET        43       43  Series.S01E01.mkv
reference     44        0  Series.S01E02.mkv
...
=== S01E01  ...
  variants fre: SWAPPED by unique lines (0 -> 1 hits) [#7:0/1, #15:0/0]
PLAN  Series.S01E01.mkv : 43 of 43 planned subtitle tracks would change
    #2   Undetermined                       -> English
    #3   Undetermined                       -> English [SDH]
    #7   Undetermined                       -> French [French (Canada)]
    ...
Simulation: 219 of 219 subtitle tracks in 5 file(s) would change; 0 need review. Nothing was written.
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `<path>` | required | A folder, or a single `.mkv`. |
| `--apply` | off | Write the tags. Without it the run is a simulation only. |
| `--reference <file>` | auto | The tagged file to learn from. Auto: the file in the folder with the most subtitle tracks, at least 80% of them tagged. If there's none, the built-in profiles are used. |
| `--target <file> …` | auto | The files to tag. Auto: every file with an untagged subtitle track or a junk track name (for a single-file path: that file). |
| `--check-tags` | off | Also read the fully tagged files, to check their tags against the text. Each file is read end to end, so this takes as long as extracting it. |
| `--replace-suspects` | off | With `--apply`: replace every suspect tag that has a confident suggestion, without asking. Unsure suggestions are still asked about. |
| `--retag-all` | off | Re-identify tracks that already have a language too, and rewrite them if they differ, without asking. |
| `--fresh` | off | With `--apply`: re-analyse instead of reusing the dry run's plan. |
| `--accept-low-confidence` | off | Apply even when tracks are marked `REVIEW`. Prefer fixing `plan.json` by hand. |
| `--work-dir <folder>` | one per path, under `workRoot` | Where extracted subtitles, the plan and the report go. |
| `--mkvtoolnix-dir <folder>` | `config.json` | Overrides `mkvToolNixDir` for one run. |
| `--max-parallel <n>` | `config.json` | Overrides `maxParallel` for one run. |

**Exit codes:** `0` done · `1` error · `3` some tracks need review (dry run), or `--apply` refused
because of them.

## Configuration: `config.json`

It sits next to `fix_subs.py`. As shipped, it holds MKVToolNix's standard install folder for each OS:

```json
{
  "mkvToolNixDir": {
    "windows": "C:\\Program Files\\MKVToolNix",
    "macos": "/Applications/MKVToolNix-*.app/Contents/MacOS",
    "linux": "/usr/bin"
  },
  "maxParallel": 4,
  "workRoot": ""
}
```

| Setting | Meaning |
|---|---|
| `mkvToolNixDir` | Folder holding `mkvmerge`, `mkvextract` and `mkvpropedit`. Either one folder for every OS (`"D:\\Tools\\MKVToolNix"`), or one per OS as above. `*` matches any version (the macOS app's name includes it); the newest wins. `""` = look on `PATH`, then in the standard folders. |
| `maxParallel` | How many `.mkv` files are **extracted at the same time**. It's the slow step: subtitle packets are spread through the whole file, so each file is read end to end. The limit is the disk or network, not the CPU. Raise it for a fast local disk, lower it to 1–2 for a slow network drive or Wi-Fi. Scanning, identifying and writing take seconds and go one file at a time. |
| `workRoot` | Parent folder of the per-path work folders. `""` = the user cache folder: `%LOCALAPPDATA%\mkv-subtitle-tagger\runs` (Windows), `~/Library/Caches/mkv-subtitle-tagger/runs` (macOS), `~/.cache/mkv-subtitle-tagger/runs` (Linux). |

- **MKVToolNix installed elsewhere** (Homebrew, a portable copy…): when the configured folder doesn't
  hold the programs, the run says so and looks on `PATH` and in the standard folders instead. An
  explicit `--mkvtoolnix-dir` doesn't fall back: it stops the run.
- **Paths:** `~`, `$VAR` and (on Windows) `%VAR%` are expanded. In JSON, write Windows backslashes
  twice (`"C:\\Tools"`) or use forward slashes.
- **Precedence:** a command-line option beats `config.json`, which beats the built-in defaults.
- **Errors:** an unknown key, a wrong type or invalid JSON stops the run, so typos don't go unnoticed.
- **It holds only paths and numbers**, never secrets.

## Output files

Everything lives in the run's work folder (its path is printed at the start of each run):

| File | Content |
|---|---|
| `subs/<key>/NN.srt` (`.ass`, `.ssa`, `.vtt`) | Every extracted text subtitle track, plus `manifest.json` (key → `.mkv` path). |
| `report.txt` | The evidence for each track: similarity scores, the runner-up, markers, the first line of text, and why a track needs review. |
| `plan.json` | The decided language and name per track to change. **Editable**: fix an entry, then `--apply`. A suspect tag's entry keeps the tag and holds the suggestion under `suspect`; set `"replace": true` (or `false`) to decide without being asked. |
| `state.json` | A fingerprint of the files (size + modified time) and of the options, used to decide whether `--apply` can reuse the plan. |

## How it works

1. **Scan** each `.mkv` with `mkvmerge -J` and give each file a role: target, reference, already
   tagged, or no subtitles. A track counts as **untagged** when no player could rely on its tag:
   - the language is `und`
   - the BCP 47 tag is `und`
   - it has no language at all. mkvmerge then reports Matroska's default, English. That's recognised
     when the file's other tracks have BCP 47 tags; otherwise the tag check below finds it.
2. **Extract** every text subtitle track with `mkvextract`, several files in parallel.
   - Formats read: SRT, ASS/SSA and WebVTT.
   - Image-based tracks (PGS, VobSub) are pictures of text: they're reported and left alone.
3. **Identify** each untagged track (`identify_subs.py`):
   - **Profiles:** each track becomes a character 1–3-gram profile, compared by cosine similarity.
   - **Tracks that already have a language keep it.** They still take part, so their label isn't
     handed out twice: a plain "French" track claims the French variant its text matches best, and
     an untagged French track gets the other one.
   - **Junk names:** a tagged track named "SubRip", "SRT", "Subtitle", "Track 3"… keeps its language,
     and its name is replaced. With a reference, it takes the name of the label it matches
     ("French (Canada)", "SDH"), or none. Without one, the junk name is removed; it's replaced by
     "SDH" or a variant name when the text shows one.
   - **Suspect tags:** every tagged track that was read is also checked against the built-in profiles.
     When they're sure the text is another language, the track gets a suggestion, and the dry run
     shows a `SUSPECT` line. The tag is only replaced if you say so (see Usage).
     - **Never blocks `--apply`.**
     - **Never used as a label for other tracks.**
     - **The reference file's tags are checked too.**
   - **Forced tracks:** a track with fewer than 25% of the file's median cue count is a **forced**
     track. It's named `Forced`.
4. **Simulate** the result, then on `--apply` write it with `mkvpropedit`:
   - tracks are addressed **by UID**, not by position
   - each file is re-read afterwards to **verify**
   - default/forced flags are **never changed**

### With a reference file

- **Assign:** labels go out **one-to-one per file**, greedily, highest similarity first, so two tracks
  can't both become "Danish".
- **Near-identical variants** (fr-CA vs fr-FR, pt-PT vs pt-BR, …): when the scores tie, lines that
  appear in only one variant of the reference decide.
- **Cross-check:** a track whose language the built-in profiles confidently reject is flagged `REVIEW`,
  with their language as the suggestion. This is usually a language the reference doesn't have.

### Without a reference file: built-in profiles

- **What's matched:** `profiles.json` holds a profile per language. Tracks are matched on letter
  n-grams only, because spacing and punctuation differ between sources, not between languages.
- **Confidence:** a track is confident when its best language beats the best other language by a set
  margin (see `BUILTIN_MIN_MARGIN` in `identify_subs.py`).
  - **Close pairs:** in one file, Danish + Norwegian or Malay + Indonesian confirm each other.
  - **Too close to call** (Croatian / Serbian / Bosnian, for instance): flagged `REVIEW`.
- **Track names** are only set when the text shows them:
  - `Forced`
  - `SDH`, when one track has many sound-cue lines (`[door slams]`) and its sibling doesn't
  - `Chinese (Simplified)` / `Chinese (Traditional)`, from the script
  - Portuguese / Spanish / French regional variants, only when two tracks' variant words clearly lean
    opposite ways
- **Identical tracks:** two tracks that still look identical (e.g. fr-CA and fr-FR with the same text)
  are flagged `REVIEW`. Give one a name in `plan.json`.
- **Already tagged tracks** of the targets serve as an extra reference for the other files. Their
  labels are used only when the built-in profiles agree on the language.
- **Languages covered:**
  - Western Europe: Basque, Catalan, Danish, Dutch, English, Finnish, French, Galician, German, Icelandic, Italian, Norwegian, Portuguese, Spanish, Swedish
  - Central and Eastern Europe: Albanian, Belarusian, Bosnian, Bulgarian, Croatian, Czech, Estonian, Greek, Hungarian, Latvian, Lithuanian, Macedonian, Polish, Romanian, Russian, Serbian (Latin and Cyrillic), Slovak, Slovenian, Ukrainian
  - Middle East and Caucasus: Arabic, Armenian, Azerbaijani, Georgian, Hebrew, Persian, Turkish
  - South Asia: Bengali, Hindi, Kannada, Malayalam, Marathi, Tamil, Telugu, Urdu
  - East and Southeast Asia: Cantonese, Chinese (Simplified and Traditional), Filipino, Indonesian, Japanese, Khmer, Korean, Malay, Thai, Vietnamese
  - Central Asia and Africa: Afrikaans, Kazakh, Swahili, Uzbek

**A reference gives better names** ("Spanish (Latin America)" rather than plain "Spanish"), so pass one
with `--reference` when you have one, even from another folder.

### Reading `report.txt`

```text
  #7  cues=559  -> fre 'French (Canada)'  s=0.998 | best ('fre', 'French (Canada)') 0.998 2nd ('fre', 'French (France)') 0.998
       {'ptPT': 13, 'esES': 2}  «MAISON DE QUARTIER»
  #10 cues=473  -> dan ''                 s=0.986 | built-in, lead 0.012 over nor
  #5  cues=559  -> fre ''                 s=0.989 | built-in, lead 0.060 over cat  <-- REVIEW
       why: identical to another track of the file (fre ''): give one a name in plan.json
  #12 cues=541  kept fre (already tagged), renamed 'SubRip' -> ''
  #20 cues=566  SUSPECT: tagged eng '', the text looks pol '' (s=0.991, built-in lead 0.214) - --apply asks
```

- **Scores:** `s` is the similarity to the label it got.
  - With a reference, `best` and `2nd` are the two closest reference tracks. The same language scores
    ≥ 0.98; close relatives (Danish/Norwegian, Czech/Slovak) sit around 0.97–0.99, and the one-to-one
    assignment separates them.
  - With the built-in profiles, `lead` is how far ahead of the best other language it is.
- **Markers:** the `{…}` counts are hand-picked hints:
  - `sdh%`: share of lines with `[sound]` cues
  - `simp` / `trad` / `yue`: Simplified / Traditional / Cantonese-only characters
  - `ptBR`, `esES`, …: variant-specific words
- **`REVIEW`:** the `why:` line says what's uncertain. Any `REVIEW` makes the run exit with code 3, and
  `--apply` refuses until the plan is fixed (set `"confident": true` on entries you've checked) or
  `--accept-low-confidence` is given.

## The reference file

- **Same series and season is best:** the same subtitle vendor makes the variant tie-breaks work.
- **Same language set:** a target track whose language the reference lacks gets the closest leftover
  label and is flagged `REVIEW`, with the built-in profiles' suggestion.
- **Language detection carries over between series:** the reference mostly supplies the **set of
  labels** and their naming ("SDH", "Spanish (Latin America)", …).

## Pitfalls

- **Regional variants can be identical except for one line.** A fr-CA and a fr-FR track may differ
  only by a translated title card. With a reference, the tie-break works only when the reference shows
  that difference too. Without one, such tracks are flagged `REVIEW`.
  - **Track order is a useful cross-check:** some files sort tracks by English name ("Brazilian
    Portuguese, Bulgarian, **C**anadian French, …, **F**rench"), others by language tag (fr-CA before
    fr-FR).
- **Only ISO 639-2 codes are written** (`fre`, `por`, …), with the variant in the track name.
  - **MKVToolNix v51+** also sets the matching BCP 47 tag (`fr`), so a regional tag such as `fr-CA` is
    replaced by `fr`.
  - **Cantonese** is written as `chi` + "Cantonese".
- **There's no backup.** `mkvpropedit` only rewrites the header and every file is verified afterwards,
  but copy any file you can't afford to lose first.
- **Audio track languages aren't touched**, even when they're `und` too.

## Tests

```text
python -I -X utf8 -m unittest discover -s tests
```

- **Unit tests** need nothing else.
- **End-to-end tests** mux small subtitle-only `.mkv` files with your MKVToolNix in a temporary folder.
  They're skipped when MKVToolNix can't be found.

The sample dialogue in `tests/samples.py` was written for the tests.

## Files

| File | Role |
|---|---|
| `fix-subs.cmd` / `fix-subs` | Launchers for Windows / macOS and Linux. |
| `fix_subs.py` | Entry point: scan → extract → identify → simulate → apply. |
| `extract_subs.py` | Parallel `mkvextract` of all text subtitle tracks + `manifest.json`. |
| `identify_subs.py` | Language identification → `plan.json` + `report.txt`. |
| `apply_plan.py` | Simulation or in-place write + verification of a `plan.json`. Also runs on its own. |
| `mkv_common.py` | Shared helpers: config, finding MKVToolNix, UTF-8-safe calls, display names. |
| `profiles.json` | Built-in language profiles. |
| `build_profiles.py` | Rebuilds `profiles.json` from Tatoeba (for maintainers; needs internet). |
| `config.json` | Settings: MKVToolNix folder per OS, parallel extractions, work folder. |
| `tests/` | Unit and end-to-end tests. |

## License

- **The code** is under the [MIT License](LICENSE): use, change and share it freely, in any project,
  including commercial ones, as long as the copyright notice stays with it. It comes with no
  warranty.
- **The built-in language profiles** (`profiles.json`) are derived from sentences of the
  [Tatoeba](https://tatoeba.org) project, so they stay under
  [CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/). Reusing them means crediting
  Tatoeba.
