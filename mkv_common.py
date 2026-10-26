"""Shared helpers: config.json, finding MKVToolNix, UTF-8-safe MKVToolNix calls, display names.

Every MKVToolNix call goes through run_tool(), which passes --output-charset UTF-8 and decodes the
output as UTF-8, so non-ASCII track names ("Français", "粵語") come back intact on every OS.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

TOOL_DIR: Path = Path(os.path.abspath(__file__)).parent
CONFIG_PATH: Path = TOOL_DIR / "config.json"
TOOL_NAMES = ("mkvmerge", "mkvextract", "mkvpropedit")

# Built-in settings; config.json overrides them, command-line options override both.
# An empty string means "work it out": auto-detect MKVToolNix, use the per-OS cache folder.
# mkvToolNixDir may also be {"windows": ..., "macos": ..., "linux": ...}, as in the shipped config.json.
DEFAULT_CONFIG: Dict[str, Any] = {
    "mkvToolNixDir": "",
    "maxParallel": 4,
    "workRoot": "",
}
OS_KEYS = ("windows", "macos", "linux")

# Exit code of fix_subs.py / apply_plan.py meaning "some tracks need a human look" (1 = error).
EXIT_NEEDS_REVIEW: int = 3

# MKVToolNix exit codes (all programs): 0 = ok, 1 = ok with warnings, 2 = error.
TOOL_EXIT_WARNINGS: int = 1
TOOL_EXIT_ERROR: int = 2


class TaggerError(Exception):
    """An expected failure, shown to the user as a plain message (bad input, missing tool, failed write).

    exit_code lets fix_subs.py tell "needs review" (3) apart from a real error (1).
    """

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code: int = exit_code


def expand_path(value: str) -> str:
    """Expand ~, $VAR / ${VAR} and (on Windows) %VAR% in a configured path."""
    return os.path.expandvars(os.path.expanduser(value)) if value else ""


def os_key() -> str:
    """This OS's key in a per-OS setting: windows, macos or linux (any other Unix counts as linux)."""
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def default_work_root() -> str:
    """Per-OS cache folder: %LOCALAPPDATA% on Windows, ~/Library/Caches on macOS, XDG cache elsewhere."""
    home: str = os.path.expanduser("~")
    if os.name == "nt":
        base: str = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "mkv-subtitle-tagger", "runs")


def load_config() -> Dict[str, Any]:
    """Built-in defaults overridden by config.json next to the scripts (optional file).

    An unknown key, a wrong type or invalid JSON stops the run, so typos don't go unnoticed.
    """
    config: Dict[str, Any] = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            loaded: Any = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as error:
            raise TaggerError(f"Invalid JSON in {CONFIG_PATH}: {error}") from error
        if not isinstance(loaded, dict):
            raise TaggerError(f"{CONFIG_PATH} must hold a JSON object, like the example in README.md")
        for key, value in loaded.items():
            if key not in DEFAULT_CONFIG:
                raise TaggerError(f"Unknown setting '{key}' in {CONFIG_PATH} (known: {', '.join(DEFAULT_CONFIG)})")
            config[key] = value

    mkvtoolnix_dir: Any = config["mkvToolNixDir"]
    if isinstance(mkvtoolnix_dir, dict):
        unknown: List[str] = [key for key in mkvtoolnix_dir if key not in OS_KEYS]
        if unknown or not all(isinstance(value, str) for value in mkvtoolnix_dir.values()):
            raise TaggerError(f"'mkvToolNixDir' in {CONFIG_PATH} must map {', '.join(OS_KEYS)} to folder strings "
                              f"(unknown: {', '.join(unknown) or 'none'})")
        config["mkvToolNixDir"] = mkvtoolnix_dir.get(os_key(), "")
    for key in ("mkvToolNixDir", "workRoot"):
        if not isinstance(config[key], str):
            raise TaggerError(f"'{key}' in {CONFIG_PATH} must be a string (\"\" = automatic)")
    # bool is a subclass of int, so check the exact type: "maxParallel": true is a typo, not 1.
    if type(config["maxParallel"]) is not int or config["maxParallel"] < 1:
        raise TaggerError(f"'maxParallel' in {CONFIG_PATH} must be a whole number of 1 or more")

    config["mkvToolNixDir"] = expand_path(config["mkvToolNixDir"])
    config["workRoot"] = expand_path(config["workRoot"]) or default_work_root()
    return config


def executable_name(tool: str) -> str:
    return tool + ".exe" if os.name == "nt" else tool


def tools_in(directory: str) -> Optional[Dict[str, str]]:
    """{tool: full path} when all three MKVToolNix programs are in the folder, else None."""
    paths: Dict[str, str] = {}
    for tool in TOOL_NAMES:
        path: str = os.path.join(directory, executable_name(tool))
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            return None
        paths[tool] = path
    return paths


def version_sort_key(path: str) -> List[Any]:
    """Natural sort key, so "MKVToolNix-100.0.app" sorts after "MKVToolNix-95.0.app"."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path)]


def standard_mkvtoolnix_dirs() -> List[str]:
    """Where MKVToolNix usually lives when it isn't on PATH."""
    if os.name == "nt":
        roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
        return [os.path.join(root, "MKVToolNix") for root in roots if root]
    if sys.platform == "darwin":
        # The .app bundle carries the command-line programs; its name includes the version.
        apps: List[str] = sorted(glob.glob("/Applications/MKVToolNix-*.app"), key=version_sort_key, reverse=True)
        return [os.path.join(app, "Contents", "MacOS") for app in apps] + ["/opt/homebrew/bin", "/usr/local/bin"]
    return ["/usr/bin", "/usr/local/bin"]


def find_mkvtoolnix(configured_dir: str, strict: bool = False) -> Dict[str, str]:
    """Full paths of mkvmerge, mkvextract and mkvpropedit, all taken from the same folder.

    The configured folder comes first; a * in it matches any version ("MKVToolNix-*.app"), newest first.
    When it doesn't hold the programs, strict (an explicit --mkvtoolnix-dir) stops the run; otherwise
    (config.json, whose shipped value is the standard install folder) a warning is printed and PATH is
    tried, then the standard install folders.
    """
    if configured_dir:
        folders: List[str] = (sorted(glob.glob(configured_dir), key=version_sort_key, reverse=True)
                              if any(char in configured_dir for char in "*?[") else [configured_dir])
        for folder in folders:
            found: Optional[Dict[str, str]] = tools_in(folder)
            if found is not None:
                return found
        if strict:
            raise TaggerError(f"mkvmerge, mkvextract and mkvpropedit are not all in '{configured_dir}'")
        print(f"WARNING: MKVToolNix isn't in '{configured_dir}' (mkvToolNixDir in {CONFIG_PATH}) - "
              "looking on PATH and in the standard install folders instead.")

    candidates: List[str] = []
    on_path: Optional[str] = shutil.which("mkvmerge")
    if on_path:
        candidates.append(os.path.dirname(on_path))
    candidates.extend(standard_mkvtoolnix_dirs())
    for directory in candidates:
        found = tools_in(directory)
        if found is not None:
            return found
    raise TaggerError("MKVToolNix not found on PATH or in " + ", ".join(candidates or ["the standard folders"]) +
                      ". Install it from https://mkvtoolnix.download/, or set mkvToolNixDir in " + str(CONFIG_PATH))


def run_tool(executable: str, arguments: List[str]) -> subprocess.CompletedProcess:
    """Run an MKVToolNix program with UTF-8 output; exit code 2 (error) raises TaggerError.

    Exit code 1 (warnings) is returned to the caller, which decides whether to show the warnings.
    """
    command: List[str] = [executable, "--output-charset", "UTF-8"] + arguments
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode >= TOOL_EXIT_ERROR:
        raise TaggerError(f"{os.path.basename(executable)} {' '.join(arguments)} failed "
                          f"(exit {completed.returncode}):\n{tool_output(completed)}")
    return completed


def tool_output(completed: subprocess.CompletedProcess) -> str:
    """stdout + stderr of an MKVToolNix call as text (its messages go to stdout)."""
    return (completed.stdout.decode("utf-8", "replace") + completed.stderr.decode("utf-8", "replace")).strip()


def mkvmerge_version(mkvmerge: str) -> str:
    """First line of `mkvmerge --version`, e.g. "mkvmerge v46.0.0 ('No Deeper Escape') 64-bit"."""
    return tool_output(run_tool(mkvmerge, ["--version"])).splitlines()[0]


def get_mkv_info(mkvmerge: str, video_path: str) -> Dict[str, Any]:
    """Parsed `mkvmerge -J` of one file."""
    completed = run_tool(mkvmerge, ["-J", video_path])
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TaggerError(f"mkvmerge -J returned unreadable output for {video_path}: {error}") from error


def subtitle_tracks(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [track for track in info.get("tracks", []) if track.get("type") == "subtitles"]


def untagged_track_ids(info: Dict[str, Any]) -> set:
    """Ids of the subtitle tracks that have no language tag a player can rely on (`mkvmerge -J` data).

    - the legacy Language says "und" (whatever the BCP 47 tag says: older players only read Language)
    - the BCP 47 tag says "und" (newer players read it first)
    - neither element is there: mkvmerge then reports Matroska's default "eng" with no BCP 47 tag.
      That is told apart from a real English tag only when the file's other subtitle tracks carry
      BCP 47 tags (MKVToolNix v51+ writes one on every track); in older files the text check finds it.
    """
    tracks: List[Dict[str, Any]] = subtitle_tracks(info)
    file_has_ietf: bool = any(track.get("properties", {}).get("language_ietf") for track in tracks)
    untagged: set = set()
    for track in tracks:
        properties: Dict[str, Any] = track.get("properties", {})
        language: str = properties.get("language") or ""
        ietf: Optional[str] = properties.get("language_ietf")
        if language in ("", "und") or ietf == "und" or (file_has_ietf and ietf is None and language == "eng"):
            untagged.add(track["id"])
    return untagged


# Track names that say nothing about the language: muxing tools often write the codec or a generic word.
# A player shows the name, so such a track reads "SubRip" even with a correct language tag.
JUNK_NAMES = {
    "subrip", "srt", "subrip/srt", "subrip (srt)", "utf8", "utf-8", "text", "s_text/utf8", "s_text/ass",
    "s_text/ssa", "s_text/webvtt", "substation alpha", "substationalpha", "advanced substation alpha", "ssa",
    "ass", "webvtt", "vtt", "pgs", "vobsub", "subtitle", "subtitles", "sub", "subs", "subtitle track",
    "untitled", "unknown", "undetermined", "und", "none",
}
NUMBERED_JUNK_NAME = re.compile(r"^(track|subtitle|subtitles|sub|subs)\s*#?\s*\d+$")


def is_junk_name(name: Optional[str]) -> bool:
    """A non-empty track name that only names the format or a number ("SubRip", "SRT", "Track 3")."""
    normalised: str = " ".join((name or "").lower().split())
    return bool(normalised) and (normalised in JUNK_NAMES or bool(NUMBERED_JUNK_NAME.match(normalised)))


# Other codes for the languages of the built-in profiles (ISO 639-2/T, 639-3, retired codes), mapped to the
# ISO 639-2/B codes MKVToolNix writes, so a "fra" tag isn't taken for a wrong one.
LANGUAGE_ALIASES: Dict[str, str] = {
    "fra": "fre", "deu": "ger", "zho": "chi", "cmn": "chi", "yue": "chi", "nob": "nor", "nno": "nor",
    "msa": "may", "zsm": "may", "nld": "dut", "ces": "cze", "slk": "slo", "ron": "rum", "mol": "rum",
    "ell": "gre", "fas": "per", "pes": "per", "sqi": "alb", "hye": "arm", "eus": "baq", "kat": "geo",
    "isl": "ice", "mkd": "mac", "mya": "bur", "tgl": "fil", "lvs": "lav", "ekk": "est", "arb": "ara",
    "swh": "swa", "uzn": "uzb", "azj": "aze", "scc": "srp", "scr": "hrv",
}


def same_language(left: Optional[str], right: Optional[str]) -> bool:
    return LANGUAGE_ALIASES.get(left or "", left) == LANGUAGE_ALIASES.get(right or "", right)


# Text subtitle codecs that can be read, and the extension mkvextract's output gets for each.
# Anything else (PGS, VobSub, DVB: pictures of text) can't be identified without OCR and is left alone.
TEXT_SUBTITLE_EXTENSIONS: Dict[str, str] = {
    "S_TEXT/UTF8": ".srt",
    "S_TEXT/ASCII": ".srt",
    "S_TEXT/ASS": ".ass",
    "S_TEXT/SSA": ".ssa",
    "S_TEXT/WEBVTT": ".vtt",
}


def text_extension(track: Dict[str, Any]) -> Optional[str]:
    """Extension for an extracted text subtitle track, or None for an image-based one."""
    return TEXT_SUBTITLE_EXTENSIONS.get(str(track.get("properties", {}).get("codec_id", "")).upper())


def language_names(mkvmerge: str) -> Dict[str, str]:
    """ISO 639 code -> English language name, from `mkvmerge --list-languages`.

    The table's columns differ between MKVToolNix versions, so every 3-letter code column is read.
    """
    names: Dict[str, str] = {"und": "Undetermined"}
    listing: str = run_tool(mkvmerge, ["--list-languages"]).stdout.decode("utf-8", "replace")
    for line in listing.splitlines():
        columns: List[str] = [column.strip() for column in line.split("|")]
        if len(columns) < 2:
            continue
        english_name: str = columns[0].split(";")[0].strip()
        for code in columns[1:]:
            if re.fullmatch(r"[a-z]{3}", code) and code not in names:
                names[code] = english_name
    return names


def format_track_label(names: Dict[str, str], language: Optional[str], name: Optional[str]) -> str:
    """How a player will roughly show the track: "French [French (Canada)]", "English", ..."""
    code: str = language or "und"
    text: str = names.get(code) or code
    if name:
        text = f"{text} [{name}]"
    return text
