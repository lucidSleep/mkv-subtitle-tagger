"""Identify the language of untagged subtitle tracks by comparing them to a correctly tagged file.

Input is the folder written by extract_subs.py (<subs_root>/<key>/<track id>.srt + manifest.json).
Each track becomes a character n-gram profile and is matched against the profiles of the reference
file's tracks, whose language/name come from `mkvmerge -J`. Labels are assigned one-to-one per file
(greedy on similarity), forced tracks are recognised by their low cue count, and near-identical
variants (e.g. fr-CA vs fr-FR) are settled by lines that occur in only one variant of the reference.

Without a reference file, the already tagged tracks of the targets act as a partial reference and the
built-in profiles (profiles.json, see build_profiles.py) settle everything else. With a reference
file, the built-in profiles only suggest a language for a track the reference has no label left for.

identify() writes <out_dir>/plan.json (consumed by apply_plan.py) and <out_dir>/report.txt (evidence
per track), and returns the number of tracks that need review.
"""

import json
import math
import os
import re
from collections import Counter
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mkv_common import TaggerError, is_junk_name, same_language, untagged_track_ids

PROFILES_PATH: Path = Path(os.path.abspath(__file__)).parent / "profiles.json"

# A track with fewer cues than this fraction of the file's median is treated as "forced".
FORCED_CUE_RATIO: float = 0.25
# Same-language matches score >= 0.98 in practice; anything under these needs a human look.
MIN_CONFIDENT_SCORE: float = 0.95
MIN_CONFIDENT_FORCED_SCORE: float = 0.80

# Built-in profiles: a track is confident when its best language beats the best *other* language by
# this margin. Measured on real subtitle sets and on held-out Tatoeba text: the wrong answers had
# margins <= 0.003 (Croatian / Serbian / Bosnian), close right ones started at 0.004 (Norwegian vs Danish).
BUILTIN_MIN_MARGIN: float = 0.008
BUILTIN_MIN_FORCED_MARGIN: float = 0.03
# Below this similarity the language is probably not among the built-in profiles at all.
BUILTIN_MIN_SCORE: float = 0.4
# A track with at least this share of sound-cue lines ("[door slams]") is SDH, when a sibling isn't.
SDH_MIN_PERCENT: float = 10.0
# Variant names for built-in labels, told apart by the WORD_MARKERS counts: (marker key, track name).
VARIANT_NAMES: Dict[str, List[Tuple[str, str]]] = {
    "por": [("ptBR", "Portuguese (Brazil)"), ("ptPT", "Portuguese (Portugal)")],
    "spa": [("es419", "Spanish (Latin America)"), ("esES", "Spanish (Spain)")],
    "fre": [("frCA", "French (Canada)"), ("frFR", "French (France)")],
}
# A variant is named only on clear marker evidence: this many marker words, leaning this far one way.
VARIANT_MIN_MARKERS: int = 3
VARIANT_MIN_LEAN: float = 0.5

TIMESTAMP_LINE = re.compile(r"^\d\d:\d\d:\d\d[,.]\d+\s*-->\s*\d\d:\d\d:\d\d[,.]\d+")
# WebVTT may leave out the hours ("01:02.500 --> 01:04.000").
VTT_TIMESTAMP_LINE = re.compile(r"^(\d+:)?\d\d:\d\d\.\d+\s*-->\s*(\d+:)?\d\d:\d\d\.\d+")
VTT_BLOCK_KEYWORDS = ("WEBVTT", "NOTE", "STYLE", "REGION")
TAG = re.compile(r"<[^>]+>|\{[^}]*\}")
# ASS/SSA line breaks and hard spaces inside a Dialogue text.
ASS_BREAK = re.compile(r"\\[Nnh]")

SIMPLIFIED_ONLY: str = "这们说个来时为会国过还对没么关开发问题变让认请谢东车门见长话间听觉记"
TRADITIONAL_ONLY: str = "這們說個來時為會國過還對沒麼關開發問題變讓認請謝東車門見長話間聽覺記"
CANTONESE_MARKERS: str = "嘅咗喺唔佢啲冇嚟睇乜嘢俾咁哋"

# Word markers, matched on whole words (lowercased). Evidence for the report only.
WORD_MARKERS: Dict[str, List[str]] = {
    "ptBR": ["você", "vocês", "a gente", "tá", "cara", "garota", "legal"],
    "ptPT": ["estás", "tu", "rapariga", "fixe", "miúdo", "estou a", "está a", "estás a"],
    "esES": ["vosotros", "os", "vale", "tío", "habéis", "estáis", "sois", "vuestro"],
    "es419": ["ustedes", "carro", "celular", "computadora", "chamaco", "plata", "lindo"],
    "frCA": ["fin de semaine", "courriel", "cellulaire", "stationnement", "pis", "pantoute", "blonde", "char"],
    "frFR": ["week-end", "mail", "portable", "parking", "mec", "flic", "putain", "nana"],
}

Label = Tuple[str, str]  # (ISO 639-2 language, track name)


class Track:
    def __init__(self, key: str, track_id: int, path: Path) -> None:
        self.key: str = key
        self.track_id: int = track_id
        self.path: Path = path
        self.uid: Optional[int] = None
        self.cues: int = 0
        self.lines: List[str] = []
        self.undecodable: int = 0
        self.profile: Dict[str, float] = {}
        self.label: Optional[Label] = None
        # The track's own language tag when it already has one: its language is kept as is. A junk name
        # ("SubRip", "Track 3") is left out of it (junk_name), and only that name gets replaced.
        self.fixed: Optional[Label] = None
        self.tag_name: str = ""
        self.junk_name: bool = False
        # A tag the text contradicts: the track is then identified like an untagged one, but the tag is
        # only replaced when the user agrees (apply_plan.py asks).
        self.suspect: Optional[Label] = None
        # True when label is the track's own tag, which no variant swap may move.
        self.exact: bool = False
        # The verdict on an untagged track: where its label came from, its score, whether it's confident.
        self.source: str = ""
        self.score: float = 0.0
        self.confident: bool = False
        self.review_reason: str = ""
        # Built-in profile evidence: ranked (score, label), and the lead over the best other language.
        self.builtin_ranked: List[Tuple[float, "Label"]] = []
        self.margin: float = 0.0
        self.runner_up: str = ""


def read_text(track: Track) -> str:
    text: str = track.path.read_bytes().decode("utf-8-sig", errors="replace")
    # Undecodable bytes are kept as U+FFFD and reported, since they weaken the language match.
    track.undecodable = text.count("\ufffd")
    return text


def read_srt(track: Track) -> None:
    """Fill cue count and plain text lines from an .srt file."""
    for line in read_text(track).splitlines():
        stripped: str = line.strip()
        if not stripped or stripped.isdigit():
            continue
        if TIMESTAMP_LINE.match(stripped):
            track.cues += 1
            continue
        track.lines.append(TAG.sub("", stripped))


def read_vtt(track: Track) -> None:
    """Fill cue count and plain text lines from a WebVTT file (header, NOTE and STYLE blocks skipped)."""
    skipping_block: bool = False
    for line in read_text(track).splitlines():
        stripped: str = line.strip()
        if not stripped:
            skipping_block = False
            continue
        if stripped.split(" ")[0] in VTT_BLOCK_KEYWORDS:
            skipping_block = True
            continue
        if skipping_block or stripped.isdigit():
            continue
        if VTT_TIMESTAMP_LINE.match(stripped):
            track.cues += 1
            continue
        track.lines.append(TAG.sub("", stripped))


def read_ass(track: Track) -> None:
    """Fill cue count and plain text lines from an .ass/.ssa file: the text field of each Dialogue line."""
    for line in read_text(track).splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields: List[str] = line.split(",", 9)
        if len(fields) < 10:
            continue
        track.cues += 1
        # Override tags ({\i1}) go; \N line breaks split the text into lines like an .srt would.
        for part in ASS_BREAK.sub("\n", TAG.sub("", fields[9])).split("\n"):
            if part.strip():
                track.lines.append(part.strip())


SUBTITLE_READERS = {".srt": read_srt, ".vtt": read_vtt, ".ass": read_ass, ".ssa": read_ass}


def build_profile(lines: List[str]) -> Dict[str, float]:
    """L2-normalised character 1..3-gram frequency profile."""
    counts: Counter = Counter()
    for line in lines:
        padded: str = " " + re.sub(r"\s+", " ", line.lower()) + " "
        for size in (1, 2, 3):
            for start in range(len(padded) - size + 1):
                counts[padded[start:start + size]] += 1
    norm: float = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {gram: value / norm for gram, value in counts.items()}


def content_profile(profile: Dict[str, float]) -> Dict[str, float]:
    """The profile without the grams made only of spaces, digits or punctuation, re-normalised.

    Used against the built-in profiles: they come from one-line sentences while subtitles are short
    padded lines, so spacing and punctuation differ by source, not by language (without this filter,
    the space gram alone made Chinese and Japanese subtitles look Korean).
    """
    kept: Dict[str, float] = {gram: value for gram, value in profile.items() if any(char.isalpha() for char in gram)}
    norm: float = math.sqrt(sum(value * value for value in kept.values())) or 1.0
    return {gram: value / norm for gram, value in kept.items()}


def cosine(left: Dict[str, float], right: Dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(gram, 0.0) for gram, value in left.items())


def markers(track: Track) -> Dict[str, float]:
    """Hand-picked evidence for the variant decisions, shown in the report."""
    joined: str = "\n".join(track.lines)
    lowered: str = " " + re.sub(r"[^\w\s'-]", " ", joined.lower()) + " "
    lowered = re.sub(r"\s+", " ", lowered)
    result: Dict[str, float] = {}
    sdh_lines: int = sum(
        1 for line in track.lines
        if re.search(r"[\[\]♪（）［］]|^\(.*\)$|^[A-Z][A-Z .'-]{2,}:", line)
    )
    result["sdh%"] = round(100.0 * sdh_lines / max(1, len(track.lines)), 1)
    result["simp"] = sum(joined.count(char) for char in SIMPLIFIED_ONLY)
    result["trad"] = sum(joined.count(char) for char in TRADITIONAL_ONLY)
    result["yue"] = sum(joined.count(char) for char in CANTONESE_MARKERS)
    for key, words in WORD_MARKERS.items():
        result[key] = sum(lowered.count(" " + word + " ") for word in words)
    if track.undecodable:
        result["UNDECODABLE"] = track.undecodable
    return result


def reference_labels(info: Dict[str, Any]) -> Dict[int, Label]:
    """track id -> (language, name) for the subtitle tracks of the correctly tagged file (`mkvmerge -J`).

    A track without a usable tag gets "und"; a junk name is left out.
    """
    labels: Dict[int, Label] = {}
    untagged: set = untagged_track_ids(info)
    for track in info["tracks"]:
        if track["type"] != "subtitles":
            continue
        properties = track["properties"]
        language: str = properties.get("language", "und")
        name: str = properties.get("track_name", "") or ""
        if is_junk_name(name):
            # "SubRip", "Track 3": not a label worth copying to other files.
            name = ""
        if track["id"] in untagged:
            language = "und"
        if language == "und" and name.startswith("Cantonese"):
            # MKVToolNix v46 has no Cantonese code; tag it as Chinese and keep the name.
            language = "chi"
        labels[track["id"]] = (language, name)
    return labels


def load_tracks(subs_root: Path, key: str, info: Dict[str, Any], keep_tags: bool) -> List[Track]:
    """Read the extracted tracks of one file. With keep_tags, tracks already tagged in `info` are fixed."""
    properties: Dict[int, Dict[str, Any]] = {track["id"]: track.get("properties", {})
                                             for track in info.get("tracks", []) if track.get("type") == "subtitles"}
    untagged: set = untagged_track_ids(info)
    tracks: List[Track] = []
    paths: List[Path] = [path for path in (subs_root / key).iterdir()
                         if path.suffix.lower() in SUBTITLE_READERS and path.stem.isdigit()]
    for path in sorted(paths, key=lambda candidate: int(candidate.stem)):
        track = Track(key, int(path.stem), path)
        track_properties: Dict[str, Any] = properties.get(track.track_id, {})
        track.uid = track_properties.get("uid")
        track.tag_name = track_properties.get("track_name") or ""
        language: str = track_properties.get("language") or "und"
        if keep_tags and track.track_id not in untagged:
            track.junk_name = is_junk_name(track.tag_name)
            track.fixed = (language, "" if track.junk_name else track.tag_name)
        SUBTITLE_READERS[path.suffix.lower()](track)
        track.profile = build_profile(track.lines)
        tracks.append(track)
    return tracks


def variant_unique_lines(references: List[Track]) -> Dict[Label, set]:
    """For labels sharing a language, the lines found in that variant's reference and in no sibling.

    Near-identical variants (a fr-CA and a fr-FR track that differ only by one translated title card)
    get the same n-gram score, so these lines are the only evidence left.
    """
    unique: Dict[Label, set] = {}
    for reference in references:
        siblings = [other for other in references
                    if other.label[0] == reference.label[0] and other.label != reference.label]
        if not siblings:
            continue
        sibling_lines: set = set().union(*(set(other.lines) for other in siblings))
        unique[reference.label] = set(reference.lines) - sibling_lines
    return unique


def resolve_variants(tracks: List[Track], unique: Dict[Label, set]) -> List[str]:
    """Re-permute variant labels within each language group to maximise reference-unique line hits.

    Only changes the n-gram assignment when the unique-line evidence strictly prefers another
    permutation; returns a human-readable note per group that was looked at.
    """
    notes: List[str] = []
    movable = [track for track in tracks if track.label and track.label[1] != "Forced" and not track.exact]
    languages = sorted({track.label[0] for track in movable})
    for language in languages:
        group = [track for track in movable if track.label[0] == language]
        group_labels = [track.label for track in group]
        if len(group) < 2 or not all(label in unique for label in group_labels):
            continue
        hits: Dict[Tuple[int, Label], int] = {
            (track.track_id, label): len(set(track.lines) & unique[label])
            for track in group for label in group_labels
        }
        current: int = sum(hits[(track.track_id, track.label)] for track in group)
        best_permutation = max(permutations(group_labels),
                               key=lambda perm: sum(hits[(track.track_id, label)]
                                                    for track, label in zip(group, perm)))
        best: int = sum(hits[(track.track_id, label)] for track, label in zip(group, best_permutation))
        detail = ", ".join(f"#{track.track_id}:" + "/".join(str(hits[(track.track_id, label)])
                                                           for label in group_labels) for track in group)
        if best > current:
            for track, label in zip(group, best_permutation):
                track.label = label
            notes.append(f"{language}: SWAPPED by unique lines ({current} -> {best} hits) [{detail}]")
        else:
            notes.append(f"{language}: kept ({current} hits) [{detail}]")
    return notes


class BuiltinProfiles:
    """The language profiles shipped in profiles.json, built from Tatoeba by build_profiles.py."""

    def __init__(self, path: Path = PROFILES_PATH) -> None:
        if not path.exists():
            raise TaggerError(f"{path} is missing: it ships with the tool, download the tool again")
        try:
            data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            self.profiles: List[Tuple[Label, Dict[str, float]]] = [
                ((entry["language"], entry["name"]), entry["profile"]) for entry in data["profiles"]]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise TaggerError(f"{path} is damaged ({error!r}), download the tool again") from error
        self.source: str = str(data.get("source", ""))
        self.built: str = str(data.get("built", ""))

    def rank(self, track: Track) -> List[Tuple[float, Label]]:
        """(score, label) for every built-in label, best first; a label scores as its best profile."""
        content: Dict[str, float] = content_profile(track.profile)
        best: Dict[Label, float] = {}
        for label, profile in self.profiles:
            score: float = cosine(content, profile)
            if score > best.get(label, -1.0):
                best[label] = score
        return sorted(((score, label) for label, score in best.items()), key=lambda pair: pair[0], reverse=True)


def builtin_lead(ranked: List[Tuple[float, Label]], language: str) -> Tuple[float, str]:
    """How far `language` is ahead of the best other built-in language (negative: behind), and that language."""
    own: float = max((score for score, label in ranked if same_language(label[0], language)), default=0.0)
    other_score, other_label = next(((score, label) for score, label in ranked
                                     if not same_language(label[0], language)), (0.0, ("und", "")))
    return own - other_score, other_label[0]


def judge_by_reference(track: Track, ranked: List[Tuple[float, Track]]) -> None:
    """Score and confidence of a label that came from the reference tracks."""
    track.source = "reference"
    if track.label is None or track.label[0] == "und" or not ranked:
        track.score = 0.0
        track.confident = False
        track.review_reason = "no reference label left for it"
        return
    is_forced: bool = track.label[1] == "Forced"
    best_ref: Track = ranked[0][1]
    track.score = max((score for score, ref in ranked
                       if ref.label[0] == track.label[0] and (is_forced or ref.label == track.label)), default=0.0)
    needed: float = MIN_CONFIDENT_FORCED_SCORE if is_forced else MIN_CONFIDENT_SCORE
    track.confident = False
    if best_ref.label[0] != track.label[0]:
        track.review_reason = f"its best match is another language ({best_ref.label[0]})"
    elif track.score < needed:
        track.review_reason = f"similarity {track.score:.3f} is below {needed}"
    elif track.undecodable:
        track.review_reason = f"{track.undecodable} undecodable characters"
    else:
        track.confident = True
        track.review_reason = ""


def builtin_is_sure(track: Track, is_forced: bool) -> bool:
    """Whether the built-in profiles alone would label the track confidently (track.builtin_ranked filled)."""
    best_score, best_label = track.builtin_ranked[0]
    lead, _ = builtin_lead(track.builtin_ranked, best_label[0])
    needed: float = BUILTIN_MIN_FORCED_MARGIN if is_forced else BUILTIN_MIN_MARGIN
    return best_score >= BUILTIN_MIN_SCORE and lead >= needed and not track.undecodable


def forced_tracks(tracks: List[Track]) -> List[Track]:
    """The tracks of one file with fewer cues than FORCED_CUE_RATIO of the file's median (all tracks count)."""
    cue_counts = sorted(track.cues for track in tracks)
    median: int = cue_counts[len(cue_counts) // 2] if cue_counts else 0
    return [track for track in tracks if track.cues < FORCED_CUE_RATIO * median]


# Codes that don't name one language (multiple, no linguistic content, uncoded, private use qaa-qtz).
NON_LANGUAGE_CODE = re.compile(r"^(mul|zxx|mis|q[a-t][a-z])$")


def find_suspect_tags(tracks: List[Track], builtin: "BuiltinProfiles") -> None:
    """Mark the tagged tracks of one file whose text the built-in profiles are sure is another language.

    Done before any label is assigned, so a wrong tag can't claim a label: a suspect is identified like
    an untagged track, and its tag is only replaced when the user agrees (apply_plan.py asks).
    """
    forced = forced_tracks(tracks)
    for track in tracks:
        if not track.builtin_ranked:
            track.builtin_ranked = builtin.rank(track)
        if track.fixed is None or NON_LANGUAGE_CODE.match(track.fixed[0]):
            continue
        if not same_language(track.builtin_ranked[0][1][0], track.fixed[0]) and builtin_is_sure(track, track in forced):
            track.suspect = track.fixed
            track.fixed = None


def judge_by_builtin(track: Track, is_forced: bool) -> None:
    """Label a track from the built-in profiles alone (track.builtin_ranked must be filled)."""
    best_score, best_label = track.builtin_ranked[0]
    track.source = "built-in"
    track.label = (best_label[0], "Forced") if is_forced else best_label
    track.score = best_score
    track.margin, track.runner_up = builtin_lead(track.builtin_ranked, best_label[0])
    needed: float = BUILTIN_MIN_FORCED_MARGIN if is_forced else BUILTIN_MIN_MARGIN
    track.confident = False
    if track.undecodable:
        track.review_reason = f"{track.undecodable} undecodable characters"
    elif best_score < BUILTIN_MIN_SCORE:
        track.review_reason = f"similarity {best_score:.3f}: probably a language without a built-in profile"
    elif track.margin < needed:
        track.review_reason = f"too close to {track.runner_up} (margin {track.margin:.3f} < {needed})"
    else:
        track.confident = True
        track.review_reason = ""


def confirm_by_contrast(tracks: List[Track]) -> List[str]:
    """Two close languages in one file (Danish + Norwegian, Malay + Indonesian) confirm each other.

    When a track's runner-up is a sibling's language and the sibling's runner-up is the track's, swapping
    the two would lose both leads, so their combined lead counts as the margin.
    """
    notes: List[str] = []
    for track in tracks:
        if track.source != "built-in" or track.confident or not track.review_reason.startswith("too close"):
            continue
        for partner in tracks:
            if partner is track or partner.label is None or not partner.builtin_ranked:
                continue
            if partner.label[0] != track.runner_up or partner.label[1] == "Forced":
                continue
            partner_lead, partner_runner_up = builtin_lead(partner.builtin_ranked, partner.label[0])
            if partner_runner_up == track.label[0] and partner_lead > 0 \
                    and track.margin + partner_lead >= BUILTIN_MIN_MARGIN:
                track.confident = True
                track.review_reason = ""
                notes.append(f"{track.label[0]}/{partner.label[0]}: #{track.track_id} confirmed by #{partner.track_id} "
                             f"(leads {track.margin:.3f} + {partner_lead:.3f})")
                break
    return notes


def name_alike_tracks(tracks: List[Track], include_tagged: bool = False) -> List[str]:
    """Built-in labels carry no variant names, so two tracks of one language can come out identical.

    They are told apart by sound cues (SDH), then by variant marker words. A track still identical to
    another track of the file needs review. With include_tagged, a tagged track whose junk name is being
    replaced can get such a name too (its language never changes).
    """
    notes: List[str] = []
    built_in: List[Track] = [track for track in tracks
                             if (track.source == "built-in" or (include_tagged and track.junk_name and track.fixed))
                             and track.label and track.label[1] != "Forced"]
    for label in sorted({track.label for track in built_in}):
        holders: List[Track] = [track for track in built_in if track.label == label]
        others: List[Track] = [track for track in tracks if track.label == label and track not in holders]
        if len(holders) + len(others) < 2:
            continue
        language: str = label[0]
        sdh: Dict[int, float] = {track.track_id: markers(track)["sdh%"] for track in holders + others}
        sdh_holders: List[Track] = [track for track in holders if sdh[track.track_id] >= SDH_MIN_PERCENT]
        if (len(sdh_holders) == 1 and all(track.label != (language, "SDH") for track in tracks)
                and all(sdh[track.track_id] < SDH_MIN_PERCENT / 2
                        for track in holders + others if track is not sdh_holders[0])):
            sdh_holders[0].label = (language, "SDH")
            holders.remove(sdh_holders[0])
            notes.append(f"{language}: #{sdh_holders[0].track_id} named 'SDH' "
                         f"({sdh[sdh_holders[0].track_id]}% of its lines are sound cues)")
        if language in VARIANT_NAMES and holders:
            # Marker words only count as contrast: a variant's text is often the other's (fr-CA subtitles
            # that are the France text), so a name is given only when no sibling leans the same way.
            (first_key, first_name), (second_key, second_name) = VARIANT_NAMES[language]
            leaning: Dict[int, str] = {}
            for track in holders + others:
                counts: Dict[str, float] = markers(track)
                first_count, second_count = counts.get(first_key, 0), counts.get(second_key, 0)
                total = first_count + second_count
                if total >= VARIANT_MIN_MARKERS and abs(first_count - second_count) / total >= VARIANT_MIN_LEAN:
                    leaning[track.track_id] = first_name if first_count > second_count else second_name
            for track in holders:
                name: Optional[str] = leaning.get(track.track_id)
                if name and list(leaning.values()).count(name) == 1 \
                        and all(other.label != (language, name) for other in tracks):
                    track.label = (language, name)
                    notes.append(f"{language}: #{track.track_id} named {name!r} by its marker words")
    for track in built_in:
        if any(other is not track and other.label == track.label for other in tracks):
            track.confident = False
            track.review_reason = (f"identical to another track of the file ({track.label[0]} {track.label[1]!r}): "
                                   "give one a name in plan.json")
    return notes


def suspect_entry(track: Track, is_forced: bool, report: List[str]) -> dict:
    """Plan entry for a tag the text contradicts: it keeps the tag (a junk name still goes) and carries the
    suggested label, which apply_plan.py offers (or applies with --replace-suspects / "replace": true)."""
    kept_name: str = "Forced" if track.junk_name and is_forced else track.suspect[1]
    lead: float = builtin_lead(track.builtin_ranked, track.label[0])[0] if track.builtin_ranked else 0.0
    unsure: str = "" if track.confident else f"; the suggestion itself is unsure: {track.review_reason}"
    report.append(f"  #{track.track_id:<2} cues={track.cues:<4} SUSPECT: tagged {track.suspect[0]} {track.tag_name!r}, "
                  f"the text looks {track.label[0]} {track.label[1]!r} (s={track.score:.3f}, built-in lead "
                  f"{lead:.3f}{unsure}) - --apply asks")
    return {"id": track.track_id, "uid": track.uid, "language": track.suspect[0], "name": kept_name,
            "source": "tag", "cues": track.cues, "score": 0.0, "confident": True,
            "suspect": {"language": track.label[0], "name": track.label[1], "source": track.source,
                        "score": round(track.score, 4), "confident": track.confident, "why": track.review_reason},
            "replace": None}


def reference_tag_entries(tracks: List[Track], report: List[str]) -> List[dict]:
    """The reference file's own tags: a suspect one is offered for replacement (and not learned from), a junk
    name is removed. Nothing else in the reference changes."""
    forced = forced_tracks(tracks)
    entries: List[dict] = []
    for track in tracks:
        if track.suspect is not None:
            judge_by_builtin(track, track in forced)
            entries.append(suspect_entry(track, track in forced, report))
        elif track.fixed is not None and track.junk_name:
            new_name: str = "Forced" if track in forced else ""
            report.append(f"  #{track.track_id:<2} cues={track.cues:<4} kept {track.fixed[0]} (already tagged), "
                          f"renamed {track.tag_name!r} -> {new_name!r}")
            entries.append({"id": track.track_id, "uid": track.uid, "language": track.fixed[0], "name": new_name,
                            "source": "tag", "cues": track.cues, "score": 0.0, "confident": True})
    return entries


def identify_file(tracks: List[Track], references: List[Track], all_labels: set, unique: Dict[Label, set],
                  report: List[str], builtin: Optional[BuiltinProfiles] = None,
                  reference_is_complete: bool = True) -> Tuple[List[dict], int]:
    """Label the untagged tracks of one file; returns plan entries and the number of tracks needing review.

    Tracks with a fixed (existing) tag get no plan entry, but still take part so their label isn't
    handed out twice: an exact match with a reference label takes that label, and a tag without an
    exact match (e.g. plain "French" against "French (Canada)" / "French (France)") claims the closest
    reference label of its own language.

    reference_is_complete: the references are a real reference file (built-in profiles only suggest a
    label it has none left for), rather than the targets' tagged tracks (built-in profiles cross-check
    every label and settle what those tracks don't cover).
    """
    # The median uses every track, tagged or not, so a lone untagged forced track is still recognised.
    cue_counts = sorted(track.cues for track in tracks)
    median: int = cue_counts[len(cue_counts) // 2]

    scores: Dict[int, List[Tuple[float, Track]]] = {
        track.track_id: sorted(((cosine(track.profile, ref.profile), ref) for ref in references),
                               key=lambda pair: pair[0], reverse=True)
        for track in tracks
    }
    forced = forced_tracks(tracks)
    regular = [track for track in tracks if track not in forced]

    taken_tracks: set = set()
    taken_labels: set = set()
    for track in tracks:
        if track.fixed is not None and (track.fixed in all_labels or track in forced):
            track.label = track.fixed
            track.exact = True
            taken_tracks.add(track.track_id)
            if track.fixed in all_labels:
                taken_labels.add(track.fixed)

    # Greedy one-to-one assignment of reference labels to the regular tracks; a tagged track may only
    # claim a label of its own language.
    pairs = sorted(((score, track, ref) for track in regular for score, ref in scores[track.track_id]
                    if track.fixed is None or same_language(ref.label[0], track.fixed[0])),
                   key=lambda item: item[0], reverse=True)
    for score, track, ref in pairs:
        if track.track_id in taken_tracks or ref.label in taken_labels:
            continue
        track.label = ref.label
        taken_tracks.add(track.track_id)
        taken_labels.add(ref.label)
    for track in tracks:
        if track.fixed is not None and track.label is None:
            # No reference label of its language left to claim: it simply keeps its tag.
            track.label = track.fixed
            track.exact = True
    for track in forced:
        if track.fixed is None and scores[track.track_id]:
            language, _ = scores[track.track_id][0][1].label
            track.label = (language, "Forced")
    variant_notes = resolve_variants(tracks, unique)

    if references:
        report.append(f"  median cues {median}; reference labels not used: {sorted(all_labels - taken_labels)}")
        report.extend(f"  variants {note}" for note in variant_notes)
    else:
        report.append(f"  median cues {median}")

    untagged: List[Track] = [track for track in tracks if track.fixed is None]
    for track in untagged:
        judge_by_reference(track, scores[track.track_id])
    if builtin is not None:
        for track in tracks:
            if not track.builtin_ranked:
                track.builtin_ranked = builtin.rank(track)
        for track in untagged:
            if reference_is_complete:
                # The reference decides; the built-in profiles only flag. A track the reference couldn't place,
                # or whose language they confidently reject (a language missing from the reference ends up
                # with the closest leftover label), gets their language as a suggestion, marked REVIEW.
                reference_label = track.label
                if reference_label is not None and (same_language(reference_label[0], track.builtin_ranked[0][1][0])
                                                    or not builtin_is_sure(track, track in forced)):
                    continue
                judge_by_builtin(track, track in forced)
                track.confident = False
                if reference_label is None:
                    track.review_reason = "the reference has no label left for it; the built-in profiles suggest this"
                else:
                    track.review_reason = (f"the reference's closest label is {reference_label[0]} "
                                           f"{reference_label[1]!r}, but the built-in profiles say {track.label[0]}: "
                                           "probably a language the reference doesn't have")
                continue
            reference_label: Optional[Label] = track.label
            if track.confident and same_language(track.builtin_ranked[0][1][0], reference_label[0]):
                track.source = "tagged tracks"
                continue
            reference_was_confident: bool = track.confident
            judge_by_builtin(track, track in forced)
            if reference_was_confident:
                track.confident = False
                track.review_reason = (f"the tagged tracks say {reference_label[0]} {reference_label[1]!r}, "
                                       f"the built-in profiles {track.label[0]}")
        report.extend(f"  built-in {note}" for note in confirm_by_contrast(tracks)
                      + name_alike_tracks(tracks, include_tagged=not reference_is_complete))

    entries: List[dict] = []
    needs_review: int = 0
    for track in tracks:
        if track.fixed is not None:
            claim: str = "" if track.label == track.fixed else f", claims {track.label}"
            if not track.junk_name:
                report.append(f"  #{track.track_id:<2} cues={track.cues:<4} kept {track.fixed[0]} {track.fixed[1]!r} "
                              f"(already tagged{claim})")
                continue
            # The language stays; the junk name gives way to the name of the label it claims, if any.
            new_name: str = "Forced" if track in forced else (
                track.label[1] if track.label and same_language(track.label[0], track.fixed[0]) else "")
            report.append(f"  #{track.track_id:<2} cues={track.cues:<4} kept {track.fixed[0]} (already tagged{claim}), "
                          f"renamed {track.tag_name!r} -> {new_name!r}")
            entries.append({"id": track.track_id, "uid": track.uid, "language": track.fixed[0], "name": new_name,
                            "source": "tag", "cues": track.cues, "score": 0.0, "confident": True})
            continue
        if track.label is None:
            # Nothing left to assign and no built-in profiles to ask.
            track.label = ("und", "")
        if track.suspect is not None:
            entries.append(suspect_entry(track, track in forced, report))
            continue
        if not track.confident:
            needs_review += 1
        flag: str = "" if track.confident else "  <-- REVIEW"
        evidence = {key: value for key, value in markers(track).items() if value}
        first_line: str = next((line for line in track.lines if len(line) > 12), "")[:40]
        if track.source == "built-in":
            report.append(f"  #{track.track_id:<2} cues={track.cues:<4} -> {track.label[0]} {track.label[1]!r:<28} "
                          f"s={track.score:.3f} | built-in, lead {track.margin:.3f} over {track.runner_up}{flag}")
        else:
            ranked = scores[track.track_id]
            best_score, best_ref = ranked[0] if ranked else (0.0, None)
            second_score, second_ref = ranked[1] if len(ranked) > 1 else (0.0, best_ref)
            report.append(f"  #{track.track_id:<2} cues={track.cues:<4} -> {track.label[0]} {track.label[1]!r:<28} "
                          f"s={track.score:.3f} | best {best_ref.label if best_ref else None} {best_score:.3f} "
                          f"2nd {second_ref.label if second_ref else None} {second_score:.3f}{flag}")
        report.append(f"       {evidence}  «{first_line}»")
        if not track.confident:
            report.append(f"       why: {track.review_reason}")
        entries.append({"id": track.track_id, "uid": track.uid, "language": track.label[0], "name": track.label[1],
                        "source": track.source, "cues": track.cues, "score": round(track.score, 4),
                        "confident": track.confident})
    return entries, needs_review


def pool_references(files: Dict[str, List[Track]]) -> List[Track]:
    """No reference file: one reference per label, from the already tagged tracks of the targets."""
    lines_by_label: Dict[Label, List[str]] = {}
    for tracks in files.values():
        for track in tracks:
            if track.fixed is not None:
                lines_by_label.setdefault(track.fixed, []).extend(track.lines)
    pool: List[Track] = []
    for label, lines in lines_by_label.items():
        reference = Track("tagged", -1, Path())
        reference.lines = lines
        reference.profile = build_profile(lines)
        reference.label = label
        pool.append(reference)
    return pool


def identify(subs_root: Path, manifest: Dict[str, str], reference_key: Optional[str],
             infos: Dict[str, Dict[str, Any]], out_dir: Path, retag_all: bool = False,
             builtin: Optional[BuiltinProfiles] = None) -> Tuple[int, int, List[str]]:
    """Label every target in the manifest; writes plan.json + report.txt to out_dir.

    infos holds the `mkvmerge -J` of every manifest file. Tracks that already have a language tag keep
    it, unless retag_all; with the built-in profiles their text is checked too (suspect tags). reference_key
    None means there is no reference file: the built-in profiles are then required.
    Returns (tracks needing review, suspect tags, report lines).
    """
    files: Dict[str, List[Track]] = {}
    plan: Dict[str, List[dict]] = {}
    if reference_key is not None:
        if reference_key not in manifest:
            raise KeyError(f"reference key {reference_key!r} not in manifest {sorted(manifest)}")
        reference_info: Dict[str, Any] = infos[manifest[reference_key]]
        labels = reference_labels(reference_info)
        references = load_tracks(subs_root, reference_key, reference_info, keep_tags=True)
        if builtin is not None:
            find_suspect_tags(references, builtin)
        for reference in references:
            reference.label = labels[reference.track_id]
        # A reference tag the text contradicts isn't learned from.
        known = [reference for reference in references if reference.label[0] != "und" and reference.suspect is None]
        if not known:
            raise ValueError(f"reference {manifest[reference_key]} has no language-tagged subtitle tracks")
        report: List[str] = [f"reference: {manifest[reference_key]} ({len(known)} tagged subtitle tracks)"]
        reference_report: List[str] = []
        reference_entries: List[dict] = reference_tag_entries(references, reference_report)
        if reference_entries:
            plan[manifest[reference_key]] = reference_entries
            report.append(f"=== {reference_key}  {manifest[reference_key]}  (the reference: its own tags)")
            report.extend(reference_report)
    else:
        if builtin is None:
            raise ValueError("no reference file and no built-in profiles: nothing to identify the languages with")
        for key, video_path in manifest.items():
            files[key] = load_tracks(subs_root, key, infos[video_path], keep_tags=not retag_all)
            # Before pooling, so a contradicted tag doesn't become a label for the other files.
            find_suspect_tags(files[key], builtin)
        known = pool_references(files)
        report = [f"reference: none - built-in language profiles ({builtin.source}, built {builtin.built}), "
                  f"plus {len(known)} label(s) from tracks of the targets that are already tagged"]
    unique = variant_unique_lines(known)
    all_labels: set = {reference.label for reference in known}

    total_review: int = 0
    for key, video_path in manifest.items():
        if key == reference_key:
            continue
        if key in files:
            tracks = files[key]
        else:
            tracks = load_tracks(subs_root, key, infos[video_path], keep_tags=not retag_all)
            if builtin is not None and not retag_all:
                find_suspect_tags(tracks, builtin)
        if not tracks:
            report.append(f"=== {key}: no extracted subtitle tracks, skipped")
            continue
        report.append(f"=== {key}  {video_path}")
        entries, needs_review = identify_file(tracks, known, all_labels, unique, report, builtin,
                                              reference_is_complete=reference_key is not None)
        if entries:
            plan[video_path] = entries
        else:
            report.append("  every subtitle track is already tagged - nothing to identify")
        total_review += needs_review
    total_suspects: int = sum(1 for entries in plan.values() for entry in entries if "suspect" in entry)

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "plan.json"
    report_path = out_dir / "report.txt"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    report.append(f"plan: {plan_path}")
    report.append(f"tracks needing review: {total_review}")
    report.append(f"suspect tags (the text looks like another language): {total_suspects}")
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    return total_review, total_suspects, report


