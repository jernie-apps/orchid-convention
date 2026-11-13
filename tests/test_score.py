"""Tests for score_findings.py and the Swift scan corpus answer key.

The sweep test is deterministic: it proves the regex half of the answer key
end to end. The score tests feed hand-written runs; they prove the scoring
arithmetic, not any real scanner's recall.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCORE = REPO / "plugins" / "convention-core" / "scripts" / "score_findings.py"
CORPUS = REPO / "plugins" / "convention-swift" / "scan-corpus"


def run(*args):
    env = dict(os.environ)
    env.pop("ORCHID_PACKS", None)
    env.pop("ORCHID_STATE_DIR", None)
    return subprocess.run([sys.executable, str(SCORE)] + [str(a) for a in args], capture_output=True, text=True,
                          env=env, timeout=300)


def truth_rows():
    lines = (CORPUS / "truth.tsv").read_text().strip().split("\n")[1:]
    return [dict(zip(("rule", "file", "line", "layer", "required"), x.split("\t"))) for x in lines]


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orchid-score-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_run(self, name, rows):
        p = self.tmp / name
        p.write_text(json.dumps({"findings": [
            {"bucket": "violation", "rule": r["rule"], "file": r["file"], "line": int(r["line"])} for r in rows]}))
        return p

    def test_sweep_finds_every_planted_regex_violation_and_no_trap(self):
        out = run("sweep", CORPUS)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("OK: sweep recall 14/14, 0 false positive(s)", out.stdout)

    def test_sweep_fails_on_a_false_positive(self):
        copy = self.tmp / "convention-swift"
        shutil.copytree(CORPUS.parent, copy, ignore=shutil.ignore_patterns("fixtures"))
        trap = copy / "scan-corpus" / "Sources" / "Shop" / "Support" / "Extra.swift"
        trap.write_text("protocol IThing {}\n")
        out = run("sweep", copy / "scan-corpus")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("FALSE POSITIVE: swift-naming-001", out.stdout)

    def test_prepare_keeps_answers_out(self):
        dest = self.tmp / "repo"
        self.assertEqual(run("prepare", CORPUS, dest).returncode, 0)
        self.assertFalse(any(p.name == "truth.tsv" for p in dest.rglob("*")))
        self.assertTrue((dest / "Sources/Shop/Services/ReceiptMailer.swift").exists())

    def test_score_perfect_and_imperfect_runs(self):
        rows = truth_rows()
        required = [r for r in rows if r["required"] == "yes"]
        perfect = self.write_run("perfect.json", required + [r for r in rows if r["required"] == "no"])
        out = run("score", CORPUS / "truth.tsv", perfect)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"recall {len(required)}/{len(required)} required, 0 false positive", out.stdout)
        missing = self.write_run("missing.json", [r for r in required if r["layer"] == "sweep"])
        extra = dict(required[0], rule="swift-naming-001")
        noisy = self.write_run("noisy.json", required + [extra])
        out = run("score", CORPUS / "truth.tsv", perfect, missing, noisy)
        self.assertEqual(out.returncode, 1)
        self.assertIn("FALSE POSITIVE: swift-naming-001", out.stdout)
        self.assertIn("found by every run: 14/19", out.stdout)


if __name__ == "__main__":
    unittest.main()
