"""Tests for sot_graph.outcome — the W0 commit outcome labeler.

Covers the pure layer only (``label_outcomes``, ``classify_subject``,
``aggregate_outcomes``, ``outcomes_from_hand_labels``): deterministic,
no git, no DB. Synthetic records use day-granularity timestamps.
"""
from __future__ import annotations

import unittest

from sot_graph.outcome import (
    CommitOutcome,
    CommitRecord,
    aggregate_outcomes,
    classify_subject,
    label_outcomes,
    outcomes_from_hand_labels,
    parse_git_timestamp,
)

DAY = 86400
T0 = 1_700_000_000  # fixed epoch; relative spacing is what matters


def _rec(
    sha: str,
    subject: str,
    day: int,
    files: list[str],
    *,
    body: str = "",
    risk: str = "LOW",
) -> CommitRecord:
    """Synthetic record; ``day`` = days after T0."""
    return CommitRecord(
        sha=sha * 8,  # pad to a plausible-looking hex
        short_sha=sha,
        author="t",
        date="",
        timestamp=T0 + day * DAY,
        subject=subject,
        body=body,
        files=list(files),
        risk_level=risk,
    )


class TestClassifySubject(unittest.TestCase):
    def test_conventional_fix(self):
        self.assertEqual(classify_subject("fix(pack): broken range"), {"fix"})
        self.assertEqual(classify_subject("fix: nil deref"), {"fix"})
        self.assertEqual(classify_subject("hotfix(core): gate"), {"fix"})
        self.assertEqual(classify_subject("fixup! feat: x"), {"fix"})

    def test_revert_variants(self):
        self.assertEqual(classify_subject('Revert "feat: x"'), {"revert"})
        self.assertEqual(classify_subject("revert(api): bad change"), {"revert"})
        self.assertEqual(classify_subject("revert: bad change"), {"revert"})

    def test_non_fix_lookalikes(self):
        # "prefix"/"suffix" contain "fix" — must not match.
        self.assertEqual(classify_subject("feat: add prefix support"), set())
        self.assertEqual(classify_subject("docs: explain suffix"), set())
        self.assertEqual(classify_subject("feat(x): thing"), set())
        # perf is optimization, not repair evidence.
        self.assertEqual(classify_subject("perf(core): batch janitor"), set())


class TestParseGitTimestamp(unittest.TestCase):
    def test_iso_with_offset(self):
        ts = parse_git_timestamp("2026-09-10 21:47:39 +0700")
        self.assertGreater(ts, 1_700_000_000)

    def test_garbage_is_zero(self):
        self.assertEqual(parse_git_timestamp(""), 0)
        self.assertEqual(parse_git_timestamp("not a date"), 0)


class TestLabelOutcomes(unittest.TestCase):
    def test_revert_by_sha(self):
        a = _rec("aaaaaaa", "feat: risky", 0, ["a.py"])
        b = _rec("bbbbbbb", 'Revert "feat: risky"', 3, ["a.py"],
                 body=f"This reverts commit {a.sha}.")
        out = {o.short_sha: o for o in label_outcomes([a, b])}
        self.assertEqual(out["aaaaaaa"].outcome, "reverted")
        self.assertEqual(out["aaaaaaa"].reverted_by, [b.sha])
        self.assertEqual(out["bbbbbbb"].outcome, "clean")

    def test_revert_by_subject_only(self):
        a = _rec("aaaaaaa", "feat(core): risky thing", 0, ["a.py"])
        b = _rec("bbbbbbb", 'Revert "feat(core): risky thing"', 30, ["a.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b])}
        # subject match, no body needed; unbounded scan catches day-30.
        self.assertEqual(out["aaaaaaa"].outcome, "reverted")

    def test_fixup(self):
        a = _rec("aaaaaaa", "feat: add thing", 0, ["src/x.py"])
        b = _rec("bbbbbbb", "fix(x): repair edge case", 5, ["src/x.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b], window_days=14)}
        self.assertEqual(out["aaaaaaa"].outcome, "fixup")
        self.assertEqual(out["aaaaaaa"].follow_up_shas, [b.sha])
        self.assertEqual(out["bbbbbbb"].outcome, "clean")

    def test_fixup_requires_file_overlap(self):
        a = _rec("aaaaaaa", "feat: add thing", 0, ["src/x.py"])
        b = _rec("bbbbbbb", "fix(y): unrelated repair", 5, ["src/y.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b])}
        self.assertEqual(out["aaaaaaa"].outcome, "clean")

    def test_fixup_requires_strong_overlap(self):
        # One shared god-file in a big commit = churn, not evidence.
        a = _rec("aaaaaaa", "feat: big", 0,
                 ["cli.py", "a.py", "b.py", "c.py", "d.py"])
        b = _rec("bbbbbbb", "fix(cli): tweak", 5, ["cli.py", "z.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b])}
        self.assertEqual(out["aaaaaaa"].outcome, "clean")  # jaccard 1/6
        # Two shared files = strong link.
        b2 = _rec("ccccccc", "fix(cli): tweak", 5, ["cli.py", "a.py"])
        out2 = {o.short_sha: o for o in label_outcomes([a, b2])}
        self.assertEqual(out2["aaaaaaa"].outcome, "fixup")

    def test_fixup_verifier_can_veto(self):
        a = _rec("aaaaaaa", "feat: add thing", 0, ["src/x.py"])
        b = _rec("bbbbbbb", "fix(x): repair", 5, ["src/x.py"])
        out = {o.short_sha: o for o in label_outcomes(
            [a, b], verify_fixup=lambda c, d, shared: False)}
        self.assertEqual(out["aaaaaaa"].outcome, "clean")
        out2 = {o.short_sha: o for o in label_outcomes(
            [a, b], verify_fixup=lambda c, d, shared: True)}
        self.assertEqual(out2["aaaaaaa"].outcome, "fixup")

    def test_docs_and_lockfiles_do_not_link(self):
        a = _rec("aaaaaaa", "build: single-source version", 0,
                 ["docs/RELEASE.md", "pyproject.toml", "uv.lock"])
        b = _rec("bbbbbbb", "fix: dep bump", 3,
                 ["src/x.py", "uv.lock", "docs/N.md"])
        # Only shared file is the lockfile -> excluded -> clean.
        out = {o.short_sha: o for o in label_outcomes([a, b])}
        self.assertEqual(out["aaaaaaa"].outcome, "clean")

    def test_fixup_outside_window_ignored(self):
        a = _rec("aaaaaaa", "feat: add thing", 0, ["src/x.py"])
        b = _rec("bbbbbbb", "fix(x): late repair", 20, ["src/x.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b], window_days=14)}
        self.assertEqual(out["aaaaaaa"].outcome, "clean")
        self.assertTrue(out["aaaaaaa"].window_complete)

    def test_retouched_needs_two(self):
        a = _rec("aaaaaaa", "feat: hot file", 0, ["src/hot.py"])
        b = _rec("bbbbbbb", "chore: touch", 2, ["src/hot.py"])
        c = _rec("ccccccc", "refactor: again", 4, ["src/hot.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b, c], retouch_min=2)}
        self.assertEqual(out["aaaaaaa"].outcome, "retouched")
        self.assertEqual(out["aaaaaaa"].retouch_count, 2)

        out1 = {o.short_sha: o for o in label_outcomes([a, b])}
        self.assertEqual(out1["aaaaaaa"].outcome, "clean")

    def test_priority_revert_over_fixup(self):
        a = _rec("aaaaaaa", "feat: risky", 0, ["a.py"])
        b = _rec("bbbbbbb", "fix(a): tried", 2, ["a.py"])
        c = _rec("ccccccc", 'Revert "feat: risky"', 4, ["a.py"],
                 body=f"This reverts commit {a.sha}.")
        out = {o.short_sha: o for o in label_outcomes([a, b, c])}
        self.assertEqual(out["aaaaaaa"].outcome, "reverted")

    def test_window_incomplete_flag(self):
        a = _rec("aaaaaaa", "feat: old", 0, ["a.py"])
        b = _rec("bbbbbbb", "feat: mid", 3, ["b.py"])
        c = _rec("ccccccc", "feat: newest", 20, ["c.py"])
        out = {o.short_sha: o for o in label_outcomes([a, b, c], window_days=14)}
        self.assertTrue(out["aaaaaaa"].window_complete)   # 20d observed
        self.assertTrue(out["bbbbbbb"].window_complete)   # 17d observed
        self.assertFalse(out["ccccccc"].window_complete)  # 0d observed

    def test_no_files_is_clean_with_evidence(self):
        a = _rec("aaaaaaa", "chore: merge", 0, [])
        out = label_outcomes([a])
        self.assertEqual(out[0].outcome, "clean")
        self.assertIn("linkage not observable", out[0].evidence[0])

    def test_empty_and_single(self):
        self.assertEqual(label_outcomes([]), [])
        out = label_outcomes([_rec("aaaaaaa", "feat: solo", 0, ["a.py"])])
        self.assertEqual(out[0].outcome, "clean")
        self.assertFalse(out[0].window_complete)  # 0d observed < 14d window

    def test_newest_first_order(self):
        recs = [_rec("aaaaaaa", "old", 0, ["a.py"]),
                _rec("bbbbbbb", "new", 5, ["b.py"])]
        out = label_outcomes(recs)
        self.assertEqual([o.short_sha for o in out], ["bbbbbbb", "aaaaaaa"])


class TestAggregate(unittest.TestCase):
    def test_rates_and_monotonic(self):
        recs = [
            _rec("a111111", "feat: x", 0, ["a.py"], risk="HIGH"),
            _rec("b111111", "fix: x broken", 3, ["a.py"], risk="LOW"),
            _rec("c111111", "feat: y", 0, ["b.py"], risk="LOW"),
            _rec("d111111", "docs: z", 0, ["c.md"], risk="LOW"),
            _rec("e111111", "docs: newest", 20, ["d.md"], risk="LOW"),
        ]
        # b fixes a's file within window -> a=fixup (adverse HIGH);
        # b/c/d clean; e only extends the observation horizon (day 20)
        # so a..d all have window_complete=True.
        out = label_outcomes(recs)
        agg = aggregate_outcomes(out)
        self.assertEqual(agg["total"], 5)
        self.assertEqual(agg["outcome_breakdown"]["fixup"], 1)
        wc = agg["per_risk"]["window_complete"]
        self.assertEqual(wc["HIGH"]["adverse_rate"], 1.0)
        self.assertEqual(wc["LOW"]["n"], 3)  # e is window-incomplete
        self.assertEqual(wc["LOW"]["adverse_rate"], 0.0)
        self.assertTrue(agg["monotonic_adverse"])

    def test_empty(self):
        agg = aggregate_outcomes([])
        self.assertEqual(agg["total"], 0)
        self.assertIsNone(agg["monotonic_adverse"])


class TestHandLabelAgreement(unittest.TestCase):
    def test_pr_and_confusions(self):
        outcomes = [
            CommitOutcome(sha="a" * 40, short_sha="aaaaaaa", subject="s",
                          date="", risk_level="LOW", outcome="fixup"),
            CommitOutcome(sha="b" * 40, short_sha="bbbbbbb", subject="s",
                          date="", risk_level="LOW", outcome="clean"),
            CommitOutcome(sha="c" * 40, short_sha="ccccccc", subject="s",
                          date="", risk_level="LOW", outcome="retouched"),
        ]
        hand = {"aaaaaaa": "fixup", "bbbbbbb": "clean", "ccccccc": "fixup",
                "deadbeef": "clean"}
        res = outcomes_from_hand_labels(outcomes, hand)
        self.assertEqual(res["sample"], 4)
        self.assertEqual(res["matched"], 2)
        self.assertEqual(res["per_class"]["fixup"]["recall"], 0.5)
        self.assertEqual(res["per_class"]["fixup"]["precision"], 1.0)
        self.assertEqual(len(res["confusions"]), 1)
        self.assertEqual(res["confusions"][0]["sha"], "ccccccc")


if __name__ == "__main__":
    unittest.main()
