"""End-to-end tests on generated .mkv files. Needs MKVToolNix; skipped when it can't be found.

Each test muxes small subtitle-only .mkv files with mkvmerge in a temporary folder, runs fix_subs.main()
and checks the plan, the tags written and the re-runs. Nothing outside the temporary folder is touched.

Run from the repository folder (standard library only):
    python -I -X utf8 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO: Path = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import fix_subs  # noqa: E402
from mkv_common import EXIT_NEEDS_REVIEW, TaggerError, find_mkvtoolnix, get_mkv_info, load_config, subtitle_tracks  # noqa: E402
from samples import SAMPLES, write_ass, write_srt, write_vtt  # noqa: E402

WRITERS = {"srt": write_srt, "ass": write_ass, "vtt": write_vtt}
Label = Tuple[str, str]
# (sample key, file format, language written in the .mkv, track name written)
TrackSpec = Tuple[str, str, str, str]


def locate_tools() -> Tuple[Optional[Dict[str, str]], str]:
    """MKVToolNix as the tool itself would find it, or None and the reason (shown as the skip reason)."""
    try:
        return find_mkvtoolnix(load_config()["mkvToolNixDir"]), ""
    except TaggerError as error:
        return None, str(error)


TOOLS, TOOLS_PROBLEM = locate_tools()


@unittest.skipUnless(TOOLS, f"MKVToolNix not found: {TOOLS_PROBLEM}")
class EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="mkv-subtitle-tagger-test-"))
        # Best-effort cleanup of the test's own temporary folder; a leftover there is harmless.
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.videos: Path = self.folder / "videos"
        self.videos.mkdir()
        self.work_dir: Path = self.folder / "work"

    def mux(self, name: str, specs: List[TrackSpec], lines_from: int = 0) -> str:
        """A subtitle-only .mkv with one track per spec; lines_from skips sample lines (another "episode")."""
        sources: Path = self.folder / "sources" / name
        sources.mkdir(parents=True)
        command: List[str] = [TOOLS["mkvmerge"], "-q", "-o", str(self.videos / name)]
        for index, (key, file_format, language, track_name) in enumerate(specs):
            path: Path = WRITERS[file_format](sources / f"{index}.{file_format}", SAMPLES[key][lines_from:])
            command += ["--language", f"0:{language}"]
            if track_name:
                command += ["--track-name", f"0:{track_name}"]
            command.append(str(path))
        completed = subprocess.run(command, capture_output=True)
        self.assertLess(completed.returncode, 2, completed.stdout.decode("utf-8", "replace"))
        return str(self.videos / name)

    def run_tool(self, *arguments: str) -> Tuple[int, str]:
        output = io.StringIO()
        # Not a terminal: --apply must never wait for an answer to a suspect-tag question here.
        original_stdin = sys.stdin
        sys.stdin = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                code: int = fix_subs.main([str(self.videos), "--work-dir", str(self.work_dir)] + list(arguments))
        finally:
            sys.stdin = original_stdin
        return code, output.getvalue()

    def labels(self, video_path: str) -> List[Label]:
        return [(track["properties"].get("language", ""), track["properties"].get("track_name") or "")
                for track in subtitle_tracks(get_mkv_info(TOOLS["mkvmerge"], video_path))]

    def plan(self) -> Dict[str, List[dict]]:
        return json.loads((self.work_dir / "plan.json").read_text(encoding="utf-8"))

    def test_reference_workflow_dry_run_apply_and_rerun(self) -> None:
        reference = self.mux("Show.S01E01.mkv", [
            ("eng", "srt", "eng", ""), ("eng-SDH", "srt", "eng", "SDH"), ("fre", "srt", "fre", ""),
            ("ger", "srt", "ger", ""), ("por-BR", "srt", "por", "Portuguese (Brazil)"),
            ("por-PT", "srt", "por", "Portuguese")])
        # The target: other lines of the same dialogue, other track order, other subtitle formats, all "und".
        target = self.mux("Show.S01E02.mkv", [
            ("ger", "ass", "und", ""), ("eng-SDH", "vtt", "und", ""), ("por-PT", "srt", "und", ""),
            ("eng", "srt", "und", ""), ("fre", "ass", "und", ""), ("por-BR", "srt", "und", "")], lines_from=2)
        reference_before: List[Label] = self.labels(reference)
        expected: List[Label] = [("ger", ""), ("eng", "SDH"), ("por", "Portuguese"), ("eng", ""), ("fre", ""),
                                 ("por", "Portuguese (Brazil)")]

        code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("6 of 6 subtitle tracks in 1 file(s) would change; 0 need review", output)
        self.assertEqual([(entry["language"], entry["name"]) for entry in self.plan()[target]], expected)
        self.assertEqual(self.labels(target), [("und", "")] * 6, "a dry run must not write anything")

        code, output = self.run_tool("--apply")
        self.assertEqual(code, 0, output)
        self.assertIn("Reusing the plan", output)
        self.assertIn("6 tracks written, all 6 verified", output)
        self.assertEqual(self.labels(target), expected)
        self.assertEqual(self.labels(reference), reference_before, "the reference must not change")

        code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("Nothing to do", output)

    def test_no_reference_partly_tagged_file(self) -> None:
        video = self.mux("Movie.mkv", [
            ("eng", "srt", "eng", ""), ("eng-SDH", "srt", "und", ""), ("fre", "vtt", "und", ""),
            ("ita", "ass", "und", ""), ("chi-Hans", "srt", "und", ""), ("ger", "srt", "ger", "German")])

        code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("built-in language profiles", output)
        entries: List[dict] = self.plan()[video]
        self.assertEqual([entry["id"] for entry in entries], [1, 2, 3, 4], "tagged tracks stay out of the plan")

        code, output = self.run_tool("--apply")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.labels(video), [("eng", ""), ("eng", "SDH"), ("fre", ""), ("ita", ""),
                                              ("chi", "Chinese (Simplified)"), ("ger", "German")])

    def test_tracks_needing_review_block_apply(self) -> None:
        # Two French tracks with the same text: nothing tells them apart without a reference.
        video = self.mux("Movie.mkv", [("fre", "srt", "und", ""), ("fre", "srt", "und", ""),
                                       ("ger", "srt", "und", "")])

        code, output = self.run_tool()
        self.assertEqual(code, EXIT_NEEDS_REVIEW, output)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(TaggerError) as raised:
                fix_subs.main([str(self.videos), "--work-dir", str(self.work_dir), "--apply"])
        self.assertEqual(raised.exception.exit_code, EXIT_NEEDS_REVIEW)
        self.assertEqual(self.labels(video), [("und", "")] * 3, "a refused apply must not write anything")

    def test_junk_names_and_suspect_tags(self) -> None:
        # French tagged right but named "SubRip"; German text tagged English; one untagged Italian track.
        video = self.mux("Movie.mkv", [("fre", "srt", "fre", "SubRip"), ("ger", "srt", "eng", ""),
                                       ("ita", "srt", "und", "")])

        code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("renamed 'SubRip' -> ''", output)
        self.assertIn("1 suspect tag(s) for --apply to ask about", output)

        code, output = self.run_tool("--apply")
        self.assertEqual(code, 0, output)
        self.assertIn("1 suspect tag(s) kept as they are", output)
        self.assertEqual(self.labels(video), [("fre", ""), ("eng", ""), ("ita", "")])

        # Now fully tagged: only --check-tags reads it again, and --replace-suspects takes the suggestion.
        code, output = self.run_tool()
        self.assertIn("Nothing to do", output)
        code, output = self.run_tool("--check-tags", "--apply", "--replace-suspects")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.labels(video), [("fre", ""), ("ger", ""), ("ita", "")])

    def test_a_wrong_configured_folder_warns_and_falls_back(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                tools = find_mkvtoolnix(str(self.folder / "no-mkvtoolnix-here"))
            except TaggerError as error:
                self.skipTest(f"MKVToolNix is only in a custom folder here, not on PATH or a standard one: {error}")
        self.assertIn("WARNING: MKVToolNix isn't in", output.getvalue())
        self.assertTrue(os.path.isfile(tools["mkvmerge"]))
        with self.assertRaises(TaggerError):
            find_mkvtoolnix(str(self.folder / "no-mkvtoolnix-here"), strict=True)

    def test_retag_all_is_not_served_a_plan_made_without_it(self) -> None:
        self.mux("Show.S01E01.mkv", [("eng", "srt", "eng", ""), ("fre", "srt", "fre", "")])
        self.mux("Show.S01E02.mkv", [("eng", "srt", "eng", ""), ("fre", "srt", "und", "")], lines_from=2)
        code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        code, output = self.run_tool("--apply", "--retag-all")
        self.assertEqual(code, 0, output)
        self.assertIn("options changed", output)
        self.assertNotIn("Reusing the plan", output)


if __name__ == "__main__":
    unittest.main()
