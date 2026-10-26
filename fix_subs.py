"""Tag the untagged ("und") subtitle tracks of .mkv files with their real language.

Learns from a correctly tagged .mkv (the reference), or from the built-in language profiles when there
is none. Tracks that already have a language are kept as they are. Dry run (simulation, nothing written)
unless --apply is given. Usage, options and pitfalls: README.md next to this script. The fix-subs /
fix-subs.cmd launchers run this script with the right Python flags.

    fix_subs.py <folder or .mkv> [--apply] [--reference <tagged .mkv>] [--target <file> ...]
                [--retag-all] [--fresh] [--accept-low-confidence] [--work-dir <folder>]

Exit codes: 0 = done, 1 = error, 3 = some tracks need review (dry run), or --apply refused for that reason.
"""

import os
import sys

if sys.version_info < (3, 9):
    sys.exit(f"Python 3.9 or newer is needed (this is {sys.version.split()[0]}).")

# Isolated mode (-I) leaves this script's own folder off sys.path; the sibling modules live there.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from apply_plan import apply_plan
from extract_subs import extract_all
from identify_subs import BuiltinProfiles, identify
from mkv_common import (EXIT_NEEDS_REVIEW, TaggerError, find_mkvtoolnix, get_mkv_info, is_junk_name, load_config,
                        mkvmerge_version, subtitle_tracks, text_extension, untagged_track_ids)

# A file counts as a usable reference when at most this fraction of its subtitle tracks is "und".
REFERENCE_MAX_UNTAGGED_RATIO: float = 0.2
# Report lines echoed to the console; the full evidence stays in report.txt.
ECHOED_REPORT_LINE = re.compile(r"^(===|  variants|  built-in|  #.*(REVIEW|SUSPECT|renamed)|       why:"
                                r"|tracks needing review|suspect tags)")


class ScannedFile:
    def __init__(self, path: str, info: Dict[str, Any]) -> None:
        self.path: str = path
        self.name: str = os.path.basename(path)
        self.info: Dict[str, Any] = info
        tracks = subtitle_tracks(info)
        untagged_ids: set = untagged_track_ids(info)
        # Image-based tracks (PGS, VobSub) can't be read, so they never count as work.
        text_tracks = [track for track in tracks if text_extension(track) is not None]
        self.subs: int = len(tracks)
        self.images: int = len(tracks) - len(text_tracks)
        self.text: int = len(text_tracks)
        self.untagged: int = sum(1 for track in text_tracks if track["id"] in untagged_ids)
        # Tagged tracks named "SubRip", "Track 3"...: their language stays, their name gets fixed.
        self.junk_names: int = sum(1 for track in text_tracks if track["id"] not in untagged_ids
                                   and is_junk_name(track.get("properties", {}).get("track_name")))
        self.role: str = ""


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fix-subs",
        description="Tag untagged subtitle tracks in .mkv files with their real language, learned from a "
                    "correctly tagged reference .mkv, or from built-in language profiles when there is none. "
                    "Dry run unless --apply is given.")
    parser.add_argument("path", help="a folder, or a single .mkv (its folder is still scanned for a reference)")
    parser.add_argument("--apply", action="store_true",
                        help="write the tags (without it the run is a simulation only)")
    parser.add_argument("--reference", metavar="MKV",
                        help="the tagged file to learn from (default: the best tagged file in the folder, "
                             "else the built-in language profiles)")
    parser.add_argument("--target", metavar="MKV", nargs="+", action="extend",
                        help="the files to tag (default: every file with an untagged subtitle track or a junk "
                             "track name)")
    parser.add_argument("--check-tags", action="store_true",
                        help="also read the fully tagged files, to check their tags against the text")
    parser.add_argument("--replace-suspects", action="store_true",
                        help="with --apply: replace every suspect tag (text in another language) that has a "
                             "confident suggestion, without asking")
    parser.add_argument("--retag-all", action="store_true",
                        help="also re-identify tracks that already have a language tag, and rewrite them "
                             "(default: keep them)")
    parser.add_argument("--fresh", action="store_true",
                        help="with --apply: re-analyse instead of reusing the dry run's plan")
    parser.add_argument("--accept-low-confidence", action="store_true",
                        help="apply even when tracks are marked REVIEW (prefer fixing plan.json by hand)")
    parser.add_argument("--work-dir", metavar="FOLDER",
                        help="where extracted subtitles, the plan and the report go (default: one per path)")
    parser.add_argument("--mkvtoolnix-dir", metavar="FOLDER", help="overrides mkvToolNixDir in config.json")
    parser.add_argument("--max-parallel", metavar="N", type=int, help="overrides maxParallel in config.json")
    return parser.parse_args(argv)


def same_path(left: str, right: str) -> bool:
    return os.path.normcase(left) == os.path.normcase(right)


def contains_path(paths: List[str], path: str) -> bool:
    return any(same_path(candidate, path) for candidate in paths)


def resolve_video_path(video_path: str) -> str:
    # abspath, not realpath: realpath turns a mapped network drive into a UNC path on Windows.
    full_path: str = os.path.abspath(video_path)
    if not os.path.isfile(full_path):
        raise TaggerError(f"File not found: {full_path}")
    return full_path


def fingerprint(paths: List[str]) -> str:
    """Size + modified time of each file: if any changes, a saved dry-run plan is no longer trusted."""
    lines: List[str] = []
    for path in sorted(paths):
        status = os.stat(path)
        lines.append(f"{path}|{status.st_size}|{status.st_mtime_ns}")
    return "\n".join(lines)


def default_work_dir(work_root: str, full_path: str) -> str:
    """One work folder per scanned folder/file, so --apply finds the plan of the preceding dry run."""
    digest: str = hashlib.sha1(os.path.normcase(full_path).encode("utf-8")).hexdigest()[:8]
    slug: str = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(full_path) or "root")[:40]
    return os.path.join(work_root, f"{slug}-{digest}")


def print_scan_table(scan: List[ScannedFile]) -> None:
    role_width: int = max([len("Role")] + [len(entry.role) for entry in scan])
    print(f"{'Role':<{role_width}}  {'Subs':>4} {'Untagged':>8} {'Junk names':>10}  Name")
    print(f"{'----':<{role_width}}  {'----':>4} {'--------':>8} {'----------':>10}  ----")
    for entry in scan:
        print(f"{entry.role:<{role_width}}  {entry.subs:>4} {entry.untagged:>8} {entry.junk_names:>10}  {entry.name}")
    images: int = sum(entry.images for entry in scan)
    if images:
        print(f"({images} image-based subtitle track(s) - PGS, VobSub - can't be read as text: "
              "they are not counted as untagged and stay as they are.)")
    print()


def use_utf8_console() -> None:
    """The console may not be UTF-8 (output redirected on Windows without -X utf8): never crash on a name."""
    for stream in (sys.stdout, sys.stderr):
        encoding: str = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding and encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    # cmd.exe turns a quoted path ending in a backslash ("Z:\Show\") into  Z:\Show"  - catch that early.
    if os.name == "nt" and '"' in args.path:
        raise TaggerError(f"The path contains a quote character: [{args.path}]. "
                          "Remove the trailing backslash before the closing quote.")

    config: Dict[str, Any] = load_config()
    max_parallel: int = args.max_parallel if args.max_parallel and args.max_parallel > 0 else config["maxParallel"]
    tools: Dict[str, str] = (find_mkvtoolnix(args.mkvtoolnix_dir, strict=True) if args.mkvtoolnix_dir
                             else find_mkvtoolnix(config["mkvToolNixDir"]))
    mkvmerge: str = tools["mkvmerge"]

    full_path: str = os.path.abspath(args.path)
    if os.path.isdir(full_path):
        video_dir: str = full_path
        single_file: Optional[str] = None
    elif os.path.isfile(full_path):
        if os.path.splitext(full_path)[1].lower() != ".mkv":
            raise TaggerError(f"Not an .mkv file: {full_path}")
        video_dir = os.path.dirname(full_path)
        single_file = full_path
    else:
        raise TaggerError(f"Not found: {full_path}")

    work_dir = Path(args.work_dir or default_work_dir(config["workRoot"], full_path))
    subs_root: Path = work_dir / "subs"
    plan_path: Path = work_dir / "plan.json"
    report_path: Path = work_dir / "report.txt"
    state_path: Path = work_dir / "state.json"

    # --- 1. Scan: what is in the folder, and which role each file gets ------------------------------
    print(f"MKVToolNix: {mkvmerge_version(mkvmerge)} in {os.path.dirname(mkvmerge)}")
    video_names: List[str] = sorted((entry.name for entry in os.scandir(video_dir)
                                     if entry.is_file() and entry.name.lower().endswith(".mkv")), key=str.lower)
    scan: List[ScannedFile] = []
    for name in video_names:
        video_path: str = os.path.join(video_dir, name)
        scan.append(ScannedFile(video_path, get_mkv_info(mkvmerge, video_path)))

    explicit_targets: List[str] = [resolve_video_path(target) for target in args.target or []]
    reference: Optional[str] = None
    if args.reference:
        reference = resolve_video_path(args.reference)
    else:
        candidates = [entry for entry in scan
                      if entry.subs > 0 and entry.untagged <= int(entry.subs * REFERENCE_MAX_UNTAGGED_RATIO)
                      and not contains_path(explicit_targets, entry.path)
                      and not (single_file and same_path(entry.path, single_file))]
        if candidates:
            # max() keeps the first of equal counts, in folder order.
            reference = max(candidates, key=lambda entry: entry.subs).path

    def has_work(entry: ScannedFile) -> bool:
        # --check-tags: a fully tagged file is read too, so its tags can be checked against its text.
        return entry.untagged > 0 or entry.junk_names > 0 or (args.check_tags and entry.text > 0)

    if explicit_targets:
        targets: List[str] = explicit_targets
    elif single_file:
        targets = [entry.path for entry in scan if same_path(entry.path, single_file) and has_work(entry)]
    else:
        # The reference itself is never a target: its untagged tracks (if any) stay as they are.
        targets = [entry.path for entry in scan
                   if has_work(entry) and not (reference and same_path(entry.path, reference))]

    for entry in scan:
        if contains_path(targets, entry.path):
            entry.role = "TARGET" if entry.untagged or entry.junk_names or explicit_targets else "check tags"
        elif reference and same_path(entry.path, reference):
            entry.role = "reference"
        elif entry.subs == 0:
            entry.role = "no subtitles"
        elif entry.untagged == 0:
            entry.role = "already tagged"
        else:
            entry.role = "partly tagged"
    print(f"Scanned {video_dir}")
    print()
    print_scan_table(scan)

    # With --check-tags and nothing else to do, the reference (its tags are always checked) still is.
    if not targets and not (args.check_tags and reference):
        what: str = (f"{os.path.basename(single_file)} has" if single_file else f"no .mkv in {video_dir} has")
        print(f"Nothing to do: {what} untagged subtitle tracks or junk track names. Tags of fully tagged files "
              "aren't read: --check-tags checks them against the text, --target with --retag-all re-identifies them.")
        return 0
    if reference and contains_path(targets, reference):
        raise TaggerError(f"The reference file can't also be a target: {reference}")
    # Shipped with the tool; with a reference it only suggests a language for a track the reference can't place.
    builtin: BuiltinProfiles = BuiltinProfiles()

    if reference:
        reference_entry: Optional[ScannedFile] = next((entry for entry in scan if same_path(entry.path, reference)),
                                                      None)
        untagged_note: str = ""
        if reference_entry and reference_entry.untagged:
            untagged_note = f"  (its {reference_entry.untagged} untagged track(s) stay as they are)"
        print(f"Reference : {reference}{untagged_note}")
    else:
        print(f"Reference : none in the folder - using the built-in language profiles ({len(builtin.profiles)}), "
              "plus the targets' tracks that are already tagged.")
        print("            Track names (SDH, regional variants) are only set when the text shows them; "
              "a tagged .mkv of the same show (--reference) gives better names.")
    print(f"Targets   : {len(targets)} file(s)" + ("  - re-identifying tagged tracks too (--retag-all)"
                                                    if args.retag_all else ""))
    print(f"Work dir  : {work_dir}")
    print()

    # --- 2. Reuse the dry run's plan, or extract + identify ------------------------------------------
    sources: List[str] = ([reference] if reference else []) + targets
    current_fingerprint: str = fingerprint(sources)
    # Options that change the plan: a plan made without them can't be reused with them, and vice versa.
    plan_options: Dict[str, Any] = {"retag_all": args.retag_all, "check_tags": args.check_tags}
    reuse_plan: bool = False
    if args.apply and not args.fresh and state_path.exists() and plan_path.exists():
        state: Dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8-sig"))
        if state.get("fingerprint") == current_fingerprint and state.get("options") == plan_options:
            reuse_plan = True
            print(f"Reusing the plan from the dry run of {state.get('created')} - the files haven't changed since.")
            print("(Pass --fresh to re-analyse instead.)")
            print()
        else:
            print("The files or options changed since the last dry run - analysing again.")
            print()

    needs_review: int = 0
    suspects: int = 0
    if not reuse_plan:
        for stale in (state_path, plan_path, report_path):
            if stale.exists():
                stale.unlink()
        if subs_root.exists():
            shutil.rmtree(subs_root)

        infos: Dict[str, Dict[str, Any]] = {entry.path: entry.info for entry in scan}
        for video_path in sources:
            if video_path not in infos:
                infos[video_path] = get_mkv_info(mkvmerge, video_path)
        manifest: Dict[str, str] = extract_all(tools["mkvextract"], infos, sources, subs_root, max_parallel)
        reference_key: Optional[str] = next((key for key, path in manifest.items() if path == reference), None)

        needs_review, suspects, report = identify(subs_root, manifest, reference_key, infos, work_dir,
                                                  retag_all=args.retag_all, builtin=builtin)
        for line in report:
            if ECHOED_REPORT_LINE.match(line):
                print(line)
        print()

        state_path.write_text(json.dumps({"fingerprint": current_fingerprint, "options": plan_options,
                                          "reference": reference, "targets": targets,
                                          "created": datetime.now().strftime("%Y-%m-%d %H:%M")},
                                         indent=2, ensure_ascii=False), encoding="utf-8")

    # --- 3. Simulate (dry run) or apply ----------------------------------------------------------------
    if not args.apply:
        apply_plan(plan_path, tools, dry_run=True, accept_low_confidence=False,
                   replace_suspects=args.replace_suspects)
        print()
        if needs_review:
            print("WARNING: Tracks marked REVIEW need a look in the report before applying.")
        if suspects:
            print(f"NOTE: {suspects} tagged track(s) look like another language (SUSPECT). --apply asks about each "
                  "one; --replace-suspects replaces them all without asking.")
        print("Dry run only - nothing was written.")
        print(f"  Report (evidence per track): {report_path}")
        print(f"  Plan (editable)            : {plan_path}")
        print(f"  To apply                   : fix-subs \"{args.path}\" --apply")
        return EXIT_NEEDS_REVIEW if needs_review else 0

    apply_plan(plan_path, tools, dry_run=False, accept_low_confidence=args.accept_low_confidence,
               replace_suspects=args.replace_suspects)
    print()
    print(f"Done. Report: {report_path}")
    return 0


if __name__ == "__main__":
    use_utf8_console()
    try:
        sys.exit(main(sys.argv[1:]))
    except TaggerError as failure:
        print(f"ERROR: {failure}", file=sys.stderr)
        sys.exit(failure.exit_code)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)
