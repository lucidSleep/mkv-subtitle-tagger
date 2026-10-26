"""Unit tests that need no MKVToolNix: readers, matching, tagged tracks, built-in profiles, guards, config.

Run from the repository folder (standard library only):
    python -I -X utf8 -m unittest discover -s tests -t .
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO: Path = Path(os.path.abspath(__file__)).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import builtins  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402

import mkv_common  # noqa: E402
from apply_plan import apply_plan, settle_suspects  # noqa: E402
from extract_subs import episode_key  # noqa: E402
from identify_subs import (BuiltinProfiles, Label, Track, build_profile, content_profile,  # noqa: E402
                           find_suspect_tags, identify_file, read_ass, read_srt, read_vtt, variant_unique_lines)
from mkv_common import is_junk_name, same_language, untagged_track_ids  # noqa: E402
from samples import SAMPLES, write_ass, write_srt, write_vtt  # noqa: E402

Result = Dict[int, Tuple[str, str, bool]]  # track id -> (language, name, confident)


def make_track(track_id: int, lines: List[str], label: Optional[Label] = None,
               fixed: Optional[Label] = None, tag_name: Optional[str] = None) -> Track:
    """A track as load_tracks() builds it; tag_name is the name in the file (a junk one is left out of fixed)."""
    track = Track("test", track_id, Path(f"{track_id:02d}.srt"))
    track.lines = list(lines)
    track.cues = len(lines)
    track.profile = build_profile(track.lines)
    track.label = label
    track.fixed = fixed
    if fixed is not None:
        track.tag_name = fixed[1] if tag_name is None else tag_name
        track.junk_name = is_junk_name(track.tag_name)
    return track


def run_file(tracks: List[Track], references: List[Track], builtin: Optional[BuiltinProfiles] = None,
             reference_is_complete: bool = True) -> Tuple[Result, int, List[str]]:
    report: List[str] = []
    entries, needs_review = identify_file(tracks, references, {reference.label for reference in references},
                                          variant_unique_lines(references), report, builtin, reference_is_complete)
    return {entry["id"]: (entry["language"], entry["name"], entry["confident"]) for entry in entries}, \
        needs_review, report


class ReaderTests(unittest.TestCase):
    def test_srt_vtt_and_ass_give_the_same_text(self) -> None:
        lines: List[str] = SAMPLES["fre"][:6]
        with tempfile.TemporaryDirectory() as folder:
            for writer, reader, name in ((write_srt, read_srt, "01.srt"), (write_vtt, read_vtt, "02.vtt"),
                                         (write_ass, read_ass, "03.ass")):
                track = Track("t", 1, writer(Path(folder) / name, lines))
                reader(track)
                self.assertEqual(track.cues, len(lines), name)
                # Tags (<i>, {\i1}) are gone; an .ass \N break splits a line in two.
                self.assertEqual(" ".join(track.lines), " ".join(lines), name)

    def test_undecodable_bytes_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "01.srt"
            path.write_bytes(b"1\n00:00:01,000 --> 00:00:02,000\nCaf\xe9 cr\xe8me\n")
            track = Track("t", 1, path)
            read_srt(track)
            self.assertEqual(track.undecodable, 2)
            self.assertEqual(track.cues, 1)


class ProfileTests(unittest.TestCase):
    def test_content_profile_drops_spacing_and_punctuation(self) -> None:
        profile: Dict[str, float] = content_profile(build_profile(["Hello, world!", "Again: hello."]))
        for gram in (" ", ",", "!", ", ", " ,"):
            self.assertNotIn(gram, profile)
        self.assertIn("hel", profile)
        self.assertAlmostEqual(sum(value * value for value in profile.values()), 1.0)

    def test_episode_keys_are_unique(self) -> None:
        used: set = set()
        self.assertEqual(episode_key("/v/Show.s01e02.mkv", used), "S01E02")
        self.assertEqual(episode_key("/v/Other.S01E02.mkv", used), "S01E02-2")
        self.assertEqual(episode_key("/v/Movie (2020).mkv", used), "Movie__2020_")


class ReferenceMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.references: List[Track] = [
            make_track(100, SAMPLES["eng"], label=("eng", "")),
            make_track(101, SAMPLES["eng-SDH"], label=("eng", "SDH")),
            make_track(102, SAMPLES["fre"], label=("fre", "")),
            make_track(103, SAMPLES["ger"], label=("ger", "")),
            make_track(104, SAMPLES["por-BR"], label=("por", "Portuguese (Brazil)")),
            make_track(105, SAMPLES["por-PT"], label=("por", "Portuguese")),
        ]

    def test_untagged_tracks_get_the_reference_labels_one_to_one(self) -> None:
        # Targets are a partial, reordered version of the reference text, as in another episode.
        order: List[str] = ["ger", "eng-SDH", "por-PT", "eng", "fre", "por-BR"]
        tracks = [make_track(index, SAMPLES[key][2:]) for index, key in enumerate(order)]
        result, needs_review, _ = run_file(tracks, self.references)
        self.assertEqual(result, {0: ("ger", "", True), 1: ("eng", "SDH", True), 2: ("por", "Portuguese", True),
                                  3: ("eng", "", True), 4: ("fre", "", True), 5: ("por", "Portuguese (Brazil)", True)})
        self.assertEqual(needs_review, 0)

    def test_tagged_tracks_are_kept_and_left_out_of_the_plan(self) -> None:
        tracks = [make_track(0, SAMPLES["eng"], fixed=("eng", "")), make_track(1, SAMPLES["eng-SDH"]),
                  make_track(2, SAMPLES["fre"], fixed=("fre", "")), make_track(3, SAMPLES["ger"])]
        result, _, report = run_file(tracks, self.references)
        self.assertEqual(result, {1: ("eng", "SDH", True), 3: ("ger", "", True)})
        self.assertTrue(any("kept eng ''" in line for line in report))

    def test_a_tagged_track_claims_its_variant_so_the_untagged_one_gets_the_other(self) -> None:
        # Two French variants that differ by one title card only, like many streaming subtitle sets.
        references = [make_track(100, SAMPLES["fre"] + ["LA MAISON DU QUÉBEC"], label=("fre", "French (Canada)")),
                      make_track(101, SAMPLES["fre"] + ["LA MAISON DE PARIS"], label=("fre", "French (France)"))]
        tracks = [make_track(0, SAMPLES["fre"] + ["LA MAISON DE PARIS"], fixed=("fre", "")),
                  make_track(1, SAMPLES["fre"] + ["LA MAISON DU QUÉBEC"])]
        result, _, _ = run_file(tracks, references)
        self.assertEqual(result[1][:2], ("fre", "French (Canada)"))

    def test_a_short_track_is_forced(self) -> None:
        tracks = [make_track(0, SAMPLES["eng"]), make_track(1, SAMPLES["fre"]), make_track(2, SAMPLES["ger"]),
                  make_track(3, SAMPLES["eng"][:3])]
        result, _, _ = run_file(tracks, self.references)
        self.assertEqual(result[3][:2], ("eng", "Forced"))


@unittest.skipUnless((REPO / "profiles.json").exists(), "profiles.json is missing")
class BuiltinProfileTests(unittest.TestCase):
    builtin: BuiltinProfiles

    @classmethod
    def setUpClass(cls) -> None:
        cls.builtin = BuiltinProfiles()

    def test_samples_get_their_language_without_any_reference(self) -> None:
        keys: List[str] = ["eng", "fre", "ger", "ita", "spa", "chi-Hans", "chi-Hant"]
        tracks = [make_track(index, SAMPLES[key]) for index, key in enumerate(keys)]
        result, needs_review, _ = run_file(tracks, [], self.builtin, reference_is_complete=False)
        self.assertEqual({track_id: language for track_id, (language, _, _) in result.items()},
                         {0: "eng", 1: "fre", 2: "ger", 3: "ita", 4: "spa", 5: "chi", 6: "chi"})
        self.assertEqual(result[5][1], "Chinese (Simplified)")
        self.assertEqual(result[6][1], "Chinese (Traditional)")
        self.assertEqual(needs_review, 0)

    def test_sdh_and_portuguese_variants_are_named(self) -> None:
        tracks = [make_track(0, SAMPLES["eng"]), make_track(1, SAMPLES["eng-SDH"]),
                  make_track(2, SAMPLES["por-BR"]), make_track(3, SAMPLES["por-PT"])]
        result, needs_review, _ = run_file(tracks, [], self.builtin, reference_is_complete=False)
        self.assertEqual(result, {0: ("eng", "", True), 1: ("eng", "SDH", True),
                                  2: ("por", "Portuguese (Brazil)", True), 3: ("por", "Portuguese (Portugal)", True)})
        self.assertEqual(needs_review, 0)

    def test_two_tracks_that_cant_be_told_apart_need_review(self) -> None:
        tracks = [make_track(0, SAMPLES["fre"]), make_track(1, SAMPLES["fre"][1:]), make_track(2, SAMPLES["ger"])]
        result, needs_review, _ = run_file(tracks, [], self.builtin, reference_is_complete=False)
        self.assertEqual((result[0][2], result[1][2], result[2][2]), (False, False, True))
        self.assertEqual(needs_review, 2)

    def test_a_tagged_track_of_the_same_language_is_not_duplicated(self) -> None:
        # No reference file: the tagged English track is the "reference" for English, so the untagged
        # English track must be told apart from it - here by its sound cues.
        tracks = [make_track(0, SAMPLES["eng"], fixed=("eng", "")), make_track(1, SAMPLES["eng-SDH"]),
                  make_track(2, SAMPLES["ger"])]
        pool = [make_track(100, SAMPLES["eng"], label=("eng", ""))]
        result, needs_review, _ = run_file(tracks, pool, self.builtin, reference_is_complete=False)
        self.assertEqual(result, {1: ("eng", "SDH", True), 2: ("ger", "", True)})
        self.assertEqual(needs_review, 0)

    def test_a_language_missing_from_the_reference_is_flagged_with_a_suggestion(self) -> None:
        references = [make_track(100, SAMPLES["eng"], label=("eng", "")),
                      make_track(101, SAMPLES["spa"], label=("spa", ""))]
        tracks = [make_track(0, SAMPLES["eng"]), make_track(1, SAMPLES["ita"])]
        result, needs_review, report = run_file(tracks, references, self.builtin)
        self.assertEqual(result[0], ("eng", "", True))
        self.assertEqual(result[1], ("ita", "", False))
        self.assertEqual(needs_review, 1)
        self.assertTrue(any("doesn't have" in line for line in report))


def subtitle_info(*properties: Dict[str, object]) -> Dict[str, object]:
    """A minimal `mkvmerge -J` result with one subtitle track per properties dict (ids 0, 1, ...)."""
    return {"tracks": [{"id": index, "type": "subtitles", "properties": dict(values)}
                       for index, values in enumerate(properties)]}


class TagRuleTests(unittest.TestCase):
    def test_tracks_without_a_usable_tag(self) -> None:
        # Modern file (BCP 47 tags present): und, a BCP 47 "und", and no language at all (reported "eng").
        modern = subtitle_info({"language": "und", "language_ietf": "fr"}, {"language": "fre", "language_ietf": "und"},
                               {"language": "eng"}, {"language": "fre", "language_ietf": "fr"},
                               {"language": "eng", "language_ietf": "en"})
        self.assertEqual(untagged_track_ids(modern), {0, 1, 2})
        # Older file without any BCP 47 tag: "eng" can't be told from a missing tag, so it counts as tagged.
        self.assertEqual(untagged_track_ids(subtitle_info({"language": "eng"}, {"language": "und"})), {1})

    def test_junk_names(self) -> None:
        for name in ("SubRip", "SRT", " subrip/srt ", "Track 3", "Subtitle #2", "SubStation Alpha", "und"):
            self.assertTrue(is_junk_name(name), name)
        for name in ("", None, "English", "SDH", "Forced", "French (Canada)", "Track of the Week"):
            self.assertFalse(is_junk_name(name), name)

    def test_language_code_aliases(self) -> None:
        self.assertTrue(same_language("fra", "fre"))
        self.assertTrue(same_language("nob", "nor"))
        self.assertTrue(same_language("zho", "chi"))
        self.assertFalse(same_language("eng", "fre"))


class JunkNameTests(unittest.TestCase):
    def test_with_a_reference_the_junk_name_becomes_the_claimed_label_name(self) -> None:
        references = [make_track(100, SAMPLES["fre"] + ["LA MAISON DU QUÉBEC"], label=("fre", "French (Canada)")),
                      make_track(101, SAMPLES["fre"] + ["LA MAISON DE PARIS"], label=("fre", "French (France)"))]
        tracks = [make_track(0, SAMPLES["fre"] + ["LA MAISON DU QUÉBEC"], fixed=("fra", ""), tag_name="SubRip"),
                  make_track(1, SAMPLES["fre"] + ["LA MAISON DE PARIS"])]
        result, needs_review, report = run_file(tracks, references)
        # The language code stays exactly as tagged ("fra"); only the name changes.
        self.assertEqual(result[0], ("fra", "French (Canada)", True))
        self.assertEqual(result[1][:2], ("fre", "French (France)"))
        self.assertTrue(any("renamed 'SubRip'" in line for line in report))

    @unittest.skipUnless((REPO / "profiles.json").exists(), "profiles.json is missing")
    def test_without_a_reference_the_junk_name_goes_or_becomes_sdh(self) -> None:
        tracks = [make_track(0, SAMPLES["eng-SDH"], fixed=("eng", ""), tag_name="SubRip"),
                  make_track(1, SAMPLES["eng"]), make_track(2, SAMPLES["ger"], fixed=("ger", ""), tag_name="Track 3")]
        result, needs_review, _ = run_file(tracks, [], BuiltinProfiles(), reference_is_complete=False)
        self.assertEqual(result, {0: ("eng", "SDH", True), 1: ("eng", "", True), 2: ("ger", "", True)})
        self.assertEqual(needs_review, 0)


@unittest.skipUnless((REPO / "profiles.json").exists(), "profiles.json is missing")
class SuspectTagTests(unittest.TestCase):
    builtin: BuiltinProfiles

    @classmethod
    def setUpClass(cls) -> None:
        cls.builtin = BuiltinProfiles()

    def entries(self, tracks: List[Track], references: List[Track], complete: bool) -> Dict[int, dict]:
        find_suspect_tags(tracks, self.builtin)
        report: List[str] = []
        entries, _ = identify_file(tracks, references, {reference.label for reference in references},
                                   variant_unique_lines(references), report, self.builtin, complete)
        return {entry["id"]: entry for entry in entries}

    def test_a_wrong_tag_is_reported_with_a_suggestion_and_kept(self) -> None:
        tracks = [make_track(0, SAMPLES["ger"], fixed=("eng", "")), make_track(1, SAMPLES["fre"], fixed=("fra", ""))]
        entries = self.entries(tracks, [], complete=False)
        self.assertEqual(sorted(entries), [0], "a correct tag under another code (fra) is not suspect")
        self.assertEqual((entries[0]["language"], entries[0]["replace"], entries[0]["confident"]), ("eng", None, True))
        self.assertEqual(entries[0]["suspect"]["language"], "ger")

    def test_a_wrong_tag_does_not_take_the_label_of_the_track_that_needs_it(self) -> None:
        references = [make_track(100, SAMPLES["eng"], label=("eng", "")),
                      make_track(101, SAMPLES["ger"], label=("ger", ""))]
        tracks = [make_track(0, SAMPLES["ger"][1:], fixed=("eng", "")), make_track(1, SAMPLES["eng"][1:])]
        entries = self.entries(tracks, references, complete=True)
        self.assertEqual((entries[1]["language"], entries[1]["confident"]), ("eng", True))
        self.assertEqual(entries[0]["suspect"]["language"], "ger")


class SuspectDecisionTests(unittest.TestCase):
    """settle_suspects(): what --apply does with suspect entries, before anything is written."""

    def plan(self) -> Dict[str, List[dict]]:
        def suspect(track_id: int, confident: bool) -> dict:
            return {"id": track_id, "language": "eng", "name": "", "confident": True, "replace": None,
                    "suspect": {"language": "pol", "name": "", "confident": confident, "why": ""}}
        return {"/videos/a.mkv": [suspect(0, True), suspect(1, True), suspect(2, False)]}

    def settle(self, plan: Dict[str, List[dict]], answers: List[str], interactive: bool,
               replace_suspects: bool = False) -> int:
        class Terminal(io.StringIO):
            def isatty(self) -> bool:
                return interactive
        replies = iter(answers)
        original_stdin, original_input = sys.stdin, builtins.input
        sys.stdin, builtins.input = Terminal(), lambda prompt="": next(replies)
        try:
            # The prompts' printed lines are checked through the plan instead.
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
                return settle_suspects(plan, Path(folder) / "plan.json", {}, dry_run=False,
                                       replace_suspects=replace_suspects)
        finally:
            sys.stdin, builtins.input = original_stdin, original_input

    def languages(self, plan: Dict[str, List[dict]]) -> List[str]:
        return [entry["language"] for entry in plan["/videos/a.mkv"]]

    def test_without_a_terminal_nothing_is_replaced(self) -> None:
        plan = self.plan()
        self.assertEqual(self.settle(plan, [], interactive=False), 3)
        self.assertEqual(self.languages(plan), ["eng", "eng", "eng"])

    def test_replace_suspects_takes_every_confident_suggestion(self) -> None:
        plan = self.plan()
        self.assertEqual(self.settle(plan, [], interactive=False, replace_suspects=True), 1)
        self.assertEqual(self.languages(plan), ["pol", "pol", "eng"])

    def test_answers_no_then_yes_to_all(self) -> None:
        plan = self.plan()
        # "a" covers the remaining confident suggestion; the unsure one is still asked (and answered "y").
        self.assertEqual(self.settle(plan, ["n", "a", "y"], interactive=True), 0)
        self.assertEqual(self.languages(plan), ["eng", "pol", "pol"])
        self.assertEqual([entry["replace"] for entry in plan["/videos/a.mkv"]], [False, True, True])


class ApplyGuardTests(unittest.TestCase):
    def test_low_confidence_plan_is_refused_before_any_file_is_touched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            plan_path = Path(folder) / "plan.json"
            missing_video: str = os.path.join(folder, "missing.mkv")
            plan_path.write_text(json.dumps({missing_video: [{"id": 0, "language": "eng", "name": "", "cues": 1,
                                                              "score": 0.5, "confident": False}]}), encoding="utf-8")
            # The tool paths don't exist either: the guard must stop before anything is run.
            tools = {name: os.path.join(folder, name) for name in mkv_common.TOOL_NAMES}
            with self.assertRaises(mkv_common.TaggerError) as raised:
                apply_plan(plan_path, tools, dry_run=False, accept_low_confidence=False)
            self.assertEqual(raised.exception.exit_code, mkv_common.EXIT_NEEDS_REVIEW)


class ConfigTests(unittest.TestCase):
    def load(self, content: str) -> Dict[str, object]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(content, encoding="utf-8")
            original: Path = mkv_common.CONFIG_PATH
            mkv_common.CONFIG_PATH = path
            try:
                return mkv_common.load_config()
            finally:
                mkv_common.CONFIG_PATH = original

    def test_empty_values_mean_automatic(self) -> None:
        config = self.load('{"mkvToolNixDir": "", "maxParallel": 2, "workRoot": ""}')
        self.assertEqual(config["mkvToolNixDir"], "")
        self.assertEqual(config["maxParallel"], 2)
        self.assertTrue(str(config["workRoot"]).endswith(os.path.join("mkv-subtitle-tagger", "runs")))

    def test_per_os_mkvtoolnix_folder(self) -> None:
        config = self.load('{"mkvToolNixDir": {"windows": "W:/mkv", "macos": "/Applications/M", "linux": "/opt/mkv"}}')
        self.assertEqual(config["mkvToolNixDir"], {"windows": "W:/mkv", "macos": "/Applications/M",
                                                   "linux": "/opt/mkv"}[mkv_common.os_key()])

    def test_mistakes_stop_the_run(self) -> None:
        for content in ('{"mkvToolnixDir": ""}', '{"maxParallel": true}', '{"maxParallel": 0}', '{"workRoot": 5}',
                        '["not", "an", "object"]', '{"maxParallel": 4,}', '{"mkvToolNixDir": {"win": "C:/"}}',
                        '{"mkvToolNixDir": {"linux": 5}}'):
            with self.assertRaises(mkv_common.TaggerError, msg=content):
                self.load(content)


if __name__ == "__main__":
    unittest.main()
