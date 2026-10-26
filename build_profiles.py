"""Rebuild profiles.json: the built-in language profiles used when there is no reference .mkv.

For maintainers only; users never run this. For each language below it downloads sentences from
Tatoeba (https://tatoeba.org, licence CC BY 2.0 FR), builds the same character n-gram profile that
identify_subs.py builds for a subtitle track, keeps the most frequent grams and writes profiles.json
next to this script.

    python -I -X utf8 build_profiles.py [--max-sentences N] [--top-grams K] [--cache <folder>]

--cache keeps the downloaded sentences as plain text, so a rebuild with other settings is offline.
"""

import os
import sys

# Isolated mode (-I) leaves this script's own folder off sys.path; the sibling modules live there.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import bz2
import json
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from identify_subs import SIMPLIFIED_ONLY, TRADITIONAL_ONLY, build_profile, content_profile

TATOEBA_URL: str = "https://downloads.tatoeba.org/exports/per_language/{code}/{code}_sentences.tsv.bz2"
OUTPUT_PATH: Path = Path(os.path.dirname(os.path.abspath(__file__))) / "profiles.json"
SOURCE_NOTE: str = "Tatoeba (https://tatoeba.org), sentences licensed CC BY 2.0 FR"
# Fewer sentences than this make an unreliable profile; the language is left out with a warning.
MIN_SENTENCES: int = 300

Label = Tuple[str, str]  # (ISO 639-2 code as written to the .mkv, track name)


def is_simplified(sentence: str) -> bool:
    return any(char in SIMPLIFIED_ONLY for char in sentence) and not any(char in TRADITIONAL_ONLY for char in sentence)


def is_traditional(sentence: str) -> bool:
    return any(char in TRADITIONAL_ONLY for char in sentence) and not any(char in SIMPLIFIED_ONLY for char in sentence)


def is_cyrillic(sentence: str) -> bool:
    return any("Ѐ" <= char <= "ӿ" for char in sentence)


def is_latin(sentence: str) -> bool:
    return not is_cyrillic(sentence)


# Tatoeba code -> the profiles built from it: (label, sentence filter or None for all sentences).
# The .mkv codes follow MKVToolNix's ISO 639-2 choices (fre, ger, chi, nor, may, ...).
LANGUAGES: Dict[str, List[Tuple[Label, Optional[Callable[[str], bool]]]]] = {
    "eng": [(("eng", ""), None)], "fra": [(("fre", ""), None)], "deu": [(("ger", ""), None)],
    "spa": [(("spa", ""), None)], "por": [(("por", ""), None)], "ita": [(("ita", ""), None)],
    "nld": [(("dut", ""), None)], "dan": [(("dan", ""), None)], "nob": [(("nor", ""), None)],
    "swe": [(("swe", ""), None)], "fin": [(("fin", ""), None)], "isl": [(("ice", ""), None)],
    "est": [(("est", ""), None)], "lvs": [(("lav", ""), None)], "lit": [(("lit", ""), None)],
    "pol": [(("pol", ""), None)], "ces": [(("cze", ""), None)], "slk": [(("slo", ""), None)],
    "slv": [(("slv", ""), None)], "hrv": [(("hrv", ""), None)], "bos": [(("bos", ""), None)],
    "srp": [(("srp", ""), is_latin), (("srp", ""), is_cyrillic)],
    "bul": [(("bul", ""), None)], "mkd": [(("mac", ""), None)], "rus": [(("rus", ""), None)],
    "ukr": [(("ukr", ""), None)], "bel": [(("bel", ""), None)], "ron": [(("rum", ""), None)],
    "hun": [(("hun", ""), None)], "ell": [(("gre", ""), None)], "tur": [(("tur", ""), None)],
    "ara": [(("ara", ""), None)], "heb": [(("heb", ""), None)], "pes": [(("per", ""), None)],
    "urd": [(("urd", ""), None)], "hin": [(("hin", ""), None)], "ben": [(("ben", ""), None)],
    "mar": [(("mar", ""), None)], "guj": [(("guj", ""), None)], "pan": [(("pan", ""), None)],
    "tam": [(("tam", ""), None)], "tel": [(("tel", ""), None)], "kan": [(("kan", ""), None)],
    "mal": [(("mal", ""), None)], "tha": [(("tha", ""), None)], "vie": [(("vie", ""), None)],
    "ind": [(("ind", ""), None)], "zsm": [(("may", ""), None)], "tgl": [(("fil", ""), None)],
    "khm": [(("khm", ""), None)], "kor": [(("kor", ""), None)], "jpn": [(("jpn", ""), None)],
    "cmn": [(("chi", "Chinese (Simplified)"), is_simplified), (("chi", "Chinese (Traditional)"), is_traditional)],
    "yue": [(("chi", "Cantonese"), None)],
    "cat": [(("cat", ""), None)], "eus": [(("baq", ""), None)], "glg": [(("glg", ""), None)],
    "sqi": [(("alb", ""), None)], "kat": [(("geo", ""), None)], "hye": [(("arm", ""), None)],
    "aze": [(("aze", ""), None)], "kaz": [(("kaz", ""), None)], "uzb": [(("uzb", ""), None)],
    "swh": [(("swa", ""), None)], "afr": [(("afr", ""), None)],
}


def download_sentences(code: str, max_sentences: int) -> List[str]:
    """The first max_sentences sentences of a Tatoeba per-language export (streamed, stops early)."""
    request = urllib.request.Request(TATOEBA_URL.format(code=code), headers={"User-Agent": "mkv-subtitle-tagger"})
    decompressor = bz2.BZ2Decompressor()
    pending: str = ""
    sentences: List[str] = []
    with urllib.request.urlopen(request, timeout=120) as response:
        while len(sentences) < max_sentences and not decompressor.eof:
            chunk: bytes = response.read(1 << 16)
            if not chunk:
                break
            pending += decompressor.decompress(chunk).decode("utf-8", errors="replace")
            lines: List[str] = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                # Format: sentence id <tab> language code <tab> text
                columns: List[str] = line.split("\t")
                if len(columns) >= 3 and columns[2].strip():
                    sentences.append(columns[2].strip())
    if pending.strip() and len(sentences) < max_sentences:
        columns = pending.split("\t")
        if len(columns) >= 3 and columns[2].strip():
            sentences.append(columns[2].strip())
    return sentences[:max_sentences]


def load_sentences(code: str, max_sentences: int, cache: Optional[Path]) -> List[str]:
    cache_file: Optional[Path] = cache / f"{code}.txt" if cache else None
    if cache_file and cache_file.exists():
        cached: List[str] = cache_file.read_text(encoding="utf-8").splitlines()
        if len(cached) >= max_sentences:
            return cached[:max_sentences]
    sentences: List[str] = download_sentences(code, max_sentences)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    return sentences


def top_profile(lines: List[str], top_grams: int) -> Dict[str, float]:
    """The top_grams heaviest content grams of the track-style profile, re-normalised, rounded to save space."""
    profile: Dict[str, float] = content_profile(build_profile(lines))
    kept: List[Tuple[str, float]] = sorted(profile.items(), key=lambda item: item[1], reverse=True)[:top_grams]
    norm: float = sum(value * value for _, value in kept) ** 0.5 or 1.0
    return {gram: float(f"{value / norm:.5g}") for gram, value in kept}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-sentences", type=int, default=30000, help="sentences read per language")
    parser.add_argument("--top-grams", type=int, default=800, help="grams kept per profile")
    parser.add_argument("--cache", type=Path, help="folder to keep downloaded sentences in")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="where to write (default: profiles.json)")
    args = parser.parse_args()

    profiles: List[Dict[str, object]] = []
    for code, variants in LANGUAGES.items():
        # A split language (cmn, srp) reads twice as many sentences, since each variant gets a share.
        wanted: int = args.max_sentences * (2 if len(variants) > 1 else 1)
        sentences: List[str] = load_sentences(code, wanted, args.cache)
        for label, keep in variants:
            selected: List[str] = [sentence for sentence in sentences if keep is None or keep(sentence)]
            selected = selected[:args.max_sentences]
            if len(selected) < MIN_SENTENCES:
                print(f"WARNING: {code} -> {label}: only {len(selected)} sentences, left out", file=sys.stderr)
                continue
            profiles.append({"language": label[0], "name": label[1], "tatoeba": code,
                             "sentences": len(selected), "profile": top_profile(selected, args.top_grams)})
            print(f"{code} -> {label}: {len(selected)} sentences")

    output: Dict[str, object] = {"source": SOURCE_NOTE, "built": date.today().isoformat(),
                                 "maxSentences": args.max_sentences, "topGrams": args.top_grams,
                                 "profiles": profiles}
    # newline="\n": profiles.json is tracked as LF, and text mode would end it with CRLF on Windows.
    # (Path.write_text() only takes newline= from Python 3.10.)
    with args.output.open("w", encoding="utf-8", newline="\n") as output_file:
        output_file.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {len(profiles)} profiles to {args.output} ({args.output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
