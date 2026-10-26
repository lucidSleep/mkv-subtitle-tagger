"""Extract every text subtitle track of the given .mkv files to <out_root>/<key>/<track id>.<srt|ass|ssa|vtt>.

<out_root>/manifest.json maps each key (e.g. "S06E03") to its .mkv path. Each file is read end to end
(subtitles are interleaved with the video), so several files are extracted at once. Image-based tracks
(PGS, VobSub) are skipped with a warning: they can't be read as text.
"""

import json
import os
import re
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

from mkv_common import TOOL_EXIT_ERROR, TOOL_EXIT_WARNINGS, TaggerError, subtitle_tracks, text_extension, tool_output


def episode_key(video_path: str, used_keys: set) -> str:
    """Short, unique folder name per file: the SxxEyy tag when there is one, else the sanitised base name."""
    base_name: str = os.path.splitext(os.path.basename(video_path))[0]
    episode_tag = re.search(r"S\d+E\d+", base_name, re.IGNORECASE)
    key: str = episode_tag.group(0).upper() if episode_tag else re.sub(r"[^A-Za-z0-9._-]", "_", base_name)
    candidate: str = key
    suffix: int = 2
    while candidate in used_keys:
        candidate = f"{key}-{suffix}"
        suffix += 1
    used_keys.add(candidate)
    return candidate


def extract_one(mkvextract: str, video_path: str, track_specs: List[str]) -> str:
    """Run mkvextract for one file; returns a one-line summary, raises TaggerError on failure."""
    # -q: no progress output. Errors and warnings are still printed.
    completed = subprocess.run([mkvextract, "--output-charset", "UTF-8", "-q", video_path, "tracks"] + track_specs,
                               capture_output=True)
    if completed.returncode >= TOOL_EXIT_ERROR:
        raise TaggerError(f"mkvextract failed (exit {completed.returncode}) for {video_path}:\n{tool_output(completed)}")
    summary: str = f"extracted {len(track_specs)} text subtitle tracks from {video_path}"
    if completed.returncode == TOOL_EXIT_WARNINGS:
        summary += f"\n  mkvextract warnings:\n  {tool_output(completed)}"
    return summary


def extract_all(mkvextract: str, infos: Dict[str, Dict[str, Any]], video_paths: List[str],
                out_root: Path, max_parallel: int) -> Dict[str, str]:
    """Extract all subtitle tracks of video_paths (in that order); returns and writes the manifest.

    infos holds the parsed `mkvmerge -J` of every path. Every file is attempted even when one fails,
    then all failures are reported together.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    used_keys: set = set()
    manifest: Dict[str, str] = {}
    jobs: Dict[Future, str] = {}
    failures: List[str] = []

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        for video_path in video_paths:
            key: str = episode_key(video_path, used_keys)
            manifest[key] = video_path
            out_dir: Path = out_root / key
            out_dir.mkdir(parents=True, exist_ok=True)
            track_specs: List[str] = []
            for track in subtitle_tracks(infos[video_path]):
                extension = text_extension(track)
                if extension is None:
                    print(f"WARNING: {os.path.basename(video_path)} #{track['id']} "
                          f"({track.get('codec', 'unknown codec')}) is an image-based subtitle track: "
                          "it can't be read as text and stays as it is")
                    continue
                track_specs.append(f"{track['id']}:{out_dir / ('%02d%s' % (track['id'], extension))}")
            if not track_specs:
                print(f"WARNING: No text subtitle tracks in {video_path}")
                continue
            jobs[pool.submit(extract_one, mkvextract, video_path, track_specs)] = key

        for job in as_completed(jobs):
            try:
                print(job.result())
            except TaggerError as error:
                failures.append(f"[{jobs[job]}] {error}")

    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if failures:
        raise TaggerError("Subtitle extraction failed:\n" + "\n".join(failures))
    return manifest
