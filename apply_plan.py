"""Write subtitle languages/names from plan.json into the .mkv files, in place, then verify.

mkvpropedit edits the header only (no remux), then each file is re-read to verify. Tracks are addressed
by UID; a file whose planned tracks are gone or have another UID is skipped. Only what differs is written,
so fixing a name never touches the language tag. A dry run prints the simulated result per track and
writes nothing, so it doubles as a "do the files already match the plan?" check.

Suspect tags (a tagged track whose text looks like another language) keep their tag unless the entry says
"replace": true, --replace-suspects is given (confident suggestions only), or the user answers yes when
asked. All of that is settled before anything is written.

Normally run by fix_subs.py. Standalone:
    python -I -X utf8 apply_plan.py <plan.json> [--dry-run] [--accept-low-confidence] [--replace-suspects]
                                    [--mkvtoolnix-dir <folder>]
"""

import os
import sys

# Isolated mode (-I) leaves this script's own folder off sys.path; the sibling modules live there.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mkv_common import (EXIT_NEEDS_REVIEW, TOOL_EXIT_WARNINGS, TaggerError, find_mkvtoolnix, format_track_label,
                        get_mkv_info, language_names, load_config, run_tool, subtitle_tracks, tool_output,
                        untagged_track_ids)


def track_by_id(tracks: List[Dict[str, Any]], track_id: int) -> Optional[Dict[str, Any]]:
    return next((track for track in tracks if track["id"] == track_id), None)


def changes_needed(track: Dict[str, Any], entry: Dict[str, Any], untagged: set) -> Tuple[bool, bool]:
    """(the language must be written, the name must be written) for one planned track.

    A track without a usable tag gets its language written even when mkvmerge reports the same code
    (Matroska's default "eng" for a track that has no language element at all).
    """
    properties: Dict[str, Any] = track.get("properties", {})
    language: str = entry.get("language") or "und"
    write_language: bool = language != (properties.get("language") or "und") or (
        track["id"] in untagged and language != "und")
    write_name: bool = (entry.get("name") or "") != (properties.get("track_name") or "")
    return write_language, write_name


def load_plan(plan_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    # utf-8-sig: the plan may have been hand-edited with an editor that adds a BOM.
    try:
        return json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise TaggerError(f"Invalid JSON in {plan_path} (hand edit?): {error}") from error


def ask_yes_no_all(prompt: str) -> str:
    """'y', 'n' or 'a' (yes to all); Enter means no. Ends the run, with nothing written, if input ends."""
    while True:
        try:
            answer: str = input(prompt).strip().lower()
        except EOFError as error:
            raise TaggerError("The input ended while asking about suspect tags - nothing was written.") from error
        if answer in ("", "n", "no"):
            return "n"
        if answer in ("y", "yes"):
            return "y"
        if answer in ("a", "all"):
            return "a"
        print("  Please answer y (yes), n (no) or a (yes to all the remaining ones).")


def settle_suspects(plan: Dict[str, List[Dict[str, Any]]], plan_path: Path, names: Dict[str, str],
                    dry_run: bool, replace_suspects: bool) -> int:
    """Decide every suspect tag before anything is written; returns how many are still undecided.

    A replaced entry takes the suggested language and name. The decisions are saved back to plan.json
    ("replace": true / false), so a retry doesn't ask again. A dry run never asks.
    """
    suspects: List[Tuple[str, Dict[str, Any]]] = [(video_path, entry) for video_path, entries in plan.items()
                                                  for entry in entries if entry.get("suspect")]
    yes_to_all: bool = replace_suspects
    asked: bool = False
    undecided: int = 0
    interactive: bool = not dry_run and sys.stdin is not None and sys.stdin.isatty()
    for video_path, entry in suspects:
        suggestion: Dict[str, Any] = entry["suspect"]
        if entry.get("replace") is None and yes_to_all and suggestion.get("confident"):
            entry["replace"] = True
        if entry.get("replace") is None and interactive:
            if not asked:
                print("Suspect tags - the text doesn't match the language tag:")
                asked = True
            now: str = format_track_label(names, entry["language"], entry["name"])
            after: str = format_track_label(names, suggestion["language"], suggestion["name"])
            unsure: str = "" if suggestion.get("confident") else f" (unsure: {suggestion.get('why')})"
            answer: str = ask_yes_no_all(f"  {os.path.basename(video_path)} #{entry['id']}: tagged {now}, "
                                         f"the text looks {after}{unsure}.\n  Replace the tag? [y/N/a] ")
            entry["replace"] = answer in ("y", "a")
            yes_to_all = yes_to_all or answer == "a"
        if entry.get("replace") is True:
            entry["language"], entry["name"] = suggestion["language"], suggestion["name"]
        elif entry.get("replace") is None:
            undecided += 1
    if asked:
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
    if undecided and not dry_run:
        print(f"{undecided} suspect tag(s) kept as they are: there's no terminal to ask in"
              f"{' (or their suggestion is unsure)' if replace_suspects else ''}. To replace one, set "
              f"\"replace\": true on its entry in plan.json, or pass --replace-suspects.")
        print()
    return undecided


def apply_plan(plan_path: Path, tools: Dict[str, str], dry_run: bool, accept_low_confidence: bool,
               replace_suspects: bool = False) -> None:
    """Simulate (dry_run) or write the plan; raises TaggerError when anything failed or needs review first."""
    mkvmerge: str = tools["mkvmerge"]
    plan = load_plan(plan_path)

    low_confidence: List[str] = [
        f"{os.path.basename(video_path)} #{entry['id']} -> {entry['language']} '{entry['name']}'"
        for video_path, entries in plan.items() for entry in entries if entry.get("confident") is False
    ]
    if low_confidence and not dry_run and not accept_low_confidence:
        raise TaggerError(f"Plan has {len(low_confidence)} low-confidence tracks - check report.txt, fix plan.json by "
                          "hand (set \"confident\": true on entries you've checked), or rerun with "
                          "--accept-low-confidence:\n  " + "\n  ".join(low_confidence), exit_code=EXIT_NEEDS_REVIEW)

    names: Dict[str, str] = language_names(mkvmerge)
    undecided_suspects: int = settle_suspects(plan, plan_path, names, dry_run, replace_suspects)
    failures: List[str] = []
    total_changes: int = 0
    total_tracks: int = 0
    files_to_change: int = 0

    for video_path, entries in plan.items():
        label: str = os.path.basename(video_path)
        info: Dict[str, Any] = get_mkv_info(mkvmerge, video_path)
        tracks: List[Dict[str, Any]] = subtitle_tracks(info)
        untagged: set = untagged_track_ids(info)
        total_tracks += len(entries)

        # A plan lists only the tracks it changes; each must still be there, with the same UID when known.
        problems: List[str] = []
        for entry in entries:
            track = track_by_id(tracks, int(entry["id"]))
            if track is None:
                problems.append(f"#{entry['id']} is not a subtitle track")
            elif entry.get("uid") is not None and track.get("properties", {}).get("uid") != entry["uid"]:
                problems.append(f"#{entry['id']} has another UID")
        if problems:
            failures.append(f"SKIPPED {label} : {', '.join(problems)} - the file changed since the plan was made")
            continue
        kept: int = len(tracks) - len(entries)
        kept_note: str = f" ({kept} other subtitle track(s) kept as they are)" if kept else ""

        arguments: List[str] = []
        rows: List[str] = []
        change_count: int = 0
        for entry in entries:
            track: Dict[str, Any] = track_by_id(tracks, int(entry["id"]))
            properties: Dict[str, Any] = track.get("properties", {})
            now: str = format_track_label(names, properties.get("language"), properties.get("track_name"))
            after: str = format_track_label(names, entry["language"], entry["name"])
            note: str = f"   <-- REVIEW (score {entry.get('score')})" if entry.get("confident") is False else ""
            suggestion: Optional[Dict[str, Any]] = entry.get("suspect")
            if suggestion and entry.get("replace") is None:
                unsure: str = "" if suggestion.get("confident") else ", unsure"
                note += (f"   SUSPECT: the text looks "
                         f"{format_track_label(names, suggestion['language'], suggestion['name'])}{unsure}"
                         f" - --apply asks")
            write_language, write_name = changes_needed(track, entry, untagged)
            if not (write_language or write_name):
                rows.append(f"    #{entry['id']:<3} {now:<34}    (unchanged){note}")
                continue
            change_count += 1
            rows.append(f"    #{entry['id']:<3} {now:<34} -> {after}{note}")
            arguments += ["--edit", f"track:={properties['uid']}"]
            if write_language:
                arguments += ["--set", f"language={entry['language']}"]
            if write_name and entry["name"]:
                arguments += ["--set", f"name={entry['name']}"]
            elif write_name:
                arguments += ["--delete", "name"]
        total_changes += change_count
        if change_count:
            files_to_change += 1

        if change_count == 0:
            print(f"SAME  {label} : all {len(entries)} planned subtitle tracks already match the plan{kept_note}")
            if dry_run and any("SUSPECT" in row for row in rows):
                print("\n".join(row for row in rows if "SUSPECT" in row))
                print()
            continue
        if dry_run:
            print(f"PLAN  {label} : {change_count} of {len(entries)} planned subtitle tracks would change{kept_note}")
            print("\n".join(rows))
            print()
            continue

        try:
            completed = run_tool(tools["mkvpropedit"], [video_path] + arguments)
        except TaggerError as error:
            failures.append(f"FAILED {label}: {error}")
            continue
        if completed.returncode == TOOL_EXIT_WARNINGS:
            print(f"WARNING: {label} :\n{tool_output(completed)}")

        written_info: Dict[str, Any] = get_mkv_info(mkvmerge, video_path)
        written: List[Dict[str, Any]] = subtitle_tracks(written_info)
        untagged_after: set = untagged_track_ids(written_info)
        mismatches: List[str] = []
        for entry in entries:
            track = track_by_id(written, int(entry["id"]))
            if track is None or any(changes_needed(track, entry, untagged_after)):
                mismatches.append(f"#{entry['id']}")
        if mismatches:
            failures.append(f"VERIFY FAILED {label} : tracks {', '.join(mismatches)} don't match after writing")
        else:
            print(f"OK    {label} : {change_count} tracks written, all {len(entries)} verified")

    if dry_run:
        suspects_note: str = (f"; {undecided_suspects} suspect tag(s) for --apply to ask about"
                              if undecided_suspects else "")
        print(f"Simulation: {total_changes} of {total_tracks} subtitle tracks in {files_to_change} file(s) would change; "
              f"{len(low_confidence)} need review{suspects_note}. Nothing was written.")
    if failures:
        raise TaggerError(f"{len(failures)} file(s) failed:\n" + "\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", type=Path, help="plan.json written by a fix_subs.py dry run")
    parser.add_argument("--dry-run", action="store_true", help="simulate only, write nothing")
    parser.add_argument("--accept-low-confidence", action="store_true", help="apply even with tracks marked REVIEW")
    parser.add_argument("--replace-suspects", action="store_true",
                        help="replace every suspect tag that has a confident suggestion, without asking")
    parser.add_argument("--mkvtoolnix-dir", help="folder holding mkvmerge/mkvpropedit (default: config.json)")
    args = parser.parse_args()
    config: Dict[str, Any] = load_config()
    tools: Dict[str, str] = (find_mkvtoolnix(args.mkvtoolnix_dir, strict=True) if args.mkvtoolnix_dir
                             else find_mkvtoolnix(config["mkvToolNixDir"]))
    apply_plan(args.plan, tools, args.dry_run, args.accept_low_confidence, args.replace_suspects)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TaggerError as failure:
        print(f"ERROR: {failure}", file=sys.stderr)
        sys.exit(failure.exit_code)
