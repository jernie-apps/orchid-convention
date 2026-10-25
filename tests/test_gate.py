"""Behaviour tests for the scan gate (hook.sh gate / baseline) and orchid_scan.py.

Each test uses a throwaway git repository and a throwaway pack with rule
files. The scanner's model judgement is simulated by writing a findings file
by hand: these tests prove the change set, sweep, seal and gate contract, not
the quality of any model scan.
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
SCRIPTS = REPO / "plugins" / "convention-core" / "scripts"
HOOK = SCRIPTS / "hook.sh"
SCAN = SCRIPTS / "orchid_scan.py"
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")

RULE = """---
id: {id}
stack: demo
category: {cat}
title: {title}
statement: {title}.
rationale: Test rule.
state: active
overridable: {ov}
ignorable: {ov}
scope: {scope}
severity: block
introduced: 2026-10-25
detect:
  method: {method}
{pattern}  file_glob: "**/*.demo"
  fragment_safe: false
examples:
  good:
    - "ok"
  bad:
    - "Foo"
---
"""


def rule(rid, cat, title, ov, scope, method, pattern=None):
    pat = f'  pattern: "{pattern}"\n' if pattern else ""
    return RULE.format(id=rid, cat=cat, title=title, ov=str(ov).lower(), scope=scope, method=method, pattern=pat)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="orchid-gate-")))
        pack = self.tmp / "packs" / "convention-demo"
        (pack / "rules").mkdir(parents=True)
        (pack / "pack.json").write_text(json.dumps({"stack": "demo", "files": ["**/*.demo"], "lint": None}))
        (pack / "rules" / "demo-naming-001.md").write_text(
            rule("demo-naming-001", "naming", "No Foo", True, "changed-files", "regex", "Foo"))
        (pack / "rules" / "demo-security-001.md").write_text(
            rule("demo-security-001", "security", "No secrets", False, "full-repo", "regex", "SECRET="))
        (pack / "rules" / "demo-structure-001.md").write_text(
            rule("demo-structure-001", "structure", "One type per file", True, "changed-files", "model"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.put("src/old.demo", "fine\n")
        self.put("README.md", "x\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "init")
        self.env = dict(os.environ, ORCHID_PACKS=str(self.tmp / "packs"), ORCHID_PYTHON=sys.executable)
        for k in ("ORCHID_STATE_DIR", "CLAUDE_PLUGIN_OPTION_GATED_AGENTS", "ORCHID_GATED_AGENTS"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo)] + list(args), check=True, capture_output=True)

    def put(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def hook(self, layer, event="Stop", session="s1", env=None, **extra):
        payload = dict({"session_id": session, "cwd": str(self.repo), "hook_event_name": event}, **extra)
        proc = subprocess.run([BASH, str(HOOK), layer], input=json.dumps(payload), capture_output=True,
                              text=True, env=env or self.env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def scan(self, *args, session="s1", check=True):
        proc = subprocess.run([sys.executable, str(SCAN), "--session", session] + list(args), cwd=self.repo,
                              capture_output=True, text=True, env=self.env, timeout=60)
        if check:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def seal(self, findings, session="s1", check=True):
        f = self.tmp / "findings.json"
        f.write_text(json.dumps({"findings": findings}))
        return self.scan("seal", "--findings", str(f), session=session, check=check)

    def test_change_set_respects_baseline_and_coverage(self):
        self.put("src/dirty.demo", "pre-existing\n")
        self.hook("baseline", event="SessionStart")
        self.assertEqual(self.scan("list").stdout, "")
        self.put("src/new.demo", "x\n")
        self.put("notes.txt", "not covered\n")
        self.put("src/old.demo", "changed\n")
        self.assertEqual(self.scan("list").stdout.split(), ["src/new.demo", "src/old.demo"])
        self.put("src/dirty.demo", "changed later\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "work")
        self.assertEqual(self.scan("list").stdout.split(), ["src/dirty.demo", "src/new.demo", "src/old.demo"])

    def test_hash_changes_with_content(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "one\n")
        h1 = self.scan("hash").stdout.strip()
        self.assertEqual(h1, self.scan("hash").stdout.strip())
        self.put("src/a.demo", "two\n")
        self.assertNotEqual(h1, self.scan("hash").stdout.strip())

    def test_no_change_passes_silently(self):
        self.hook("baseline", event="SessionStart")
        self.put("notes.txt", "uncovered\n")
        self.assertEqual(self.hook("gate"), {})

    def test_unsealed_blocks_twice_then_records_exit(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "x\n")
        first = self.hook("gate")
        self.assertEqual(first["decision"], "block")
        self.assertIn("--session s1 seal --findings", first["reason"])
        self.assertIn("src/a.demo", first["reason"])
        self.assertEqual(self.hook("gate")["decision"], "block")
        third = self.hook("gate")
        self.assertNotIn("decision", third)
        self.assertIn("UNSCANNED", third["systemMessage"])
        exits = (self.repo / ".git" / "orchid-convention" / "exits.jsonl").read_text()
        self.assertIn('"why": "unscanned"', exits)
        self.assertEqual(self.hook("gate"), {})

    def test_scan_in_progress_is_silent(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "x\n")
        self.scan("begin")
        self.assertEqual(self.hook("gate"), {})

    def test_clean_seal_passes(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "fine\n")
        out = json.loads(self.seal([]).stdout)
        self.assertEqual(out["verdict"], "clean")
        self.assertEqual(self.hook("gate"), {})
        self.put("src/a.demo", "edited after the seal\n")
        self.assertEqual(self.hook("gate")["decision"], "block")

    def test_sweep_overrules_a_clean_claim(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "let Foo = 1\n")
        out = json.loads(self.seal([]).stdout)
        self.assertEqual(out["verdict"], "violations")
        blocked = self.hook("gate")
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("demo-naming-001 src/a.demo:1", blocked["reason"])

    def test_scanner_violation_blocks(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "two types\n")
        self.seal([{"bucket": "violation", "rule": "demo-structure-001", "file": "src/a.demo", "line": 1,
                    "evidence": "two top-level types"}])
        self.assertIn("demo-structure-001", self.hook("gate")["reason"])

    def test_findings_are_validated(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "x\n")
        bad = self.seal([{"bucket": "violation", "rule": "demo-structure-001", "file": "src/old.demo",
                          "evidence": "e"}], check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("not in this change set", bad.stderr)
        bad = self.seal([{"bucket": "fixed", "file": "src/a.demo", "evidence": "e"}], check=False)
        self.assertIn("bucket must be one of", bad.stderr)

    def test_standing_full_repo_hit_passes_with_one_notice(self):
        self.put("src/legacy.demo", "SECRET=abc\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "legacy")
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "fine\n")
        self.assertEqual(json.loads(self.seal([]).stdout)["verdict"], "standing")
        out = self.hook("gate")
        self.assertNotIn("decision", out)
        self.assertIn("1 standing finding", out["systemMessage"])
        self.assertEqual(self.hook("gate"), {})

    def test_overrides_in_sweep(self):
        conv = self.repo / ".orchid" / "conventions"
        conv.mkdir(parents=True)
        (conv / "demo.md").write_text("## demo-naming-001\noverride: global\nreason: legacy\n\n"
                                      "## demo-security-001\noverride: global\nreason: no\n")
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "Foo\nSECRET=1\n")
        findings = json.loads(self.scan("sweep").stdout)["findings"]
        self.assertEqual([f["rule"] for f in findings], ["demo-security-001"])

    def test_rules_lists_only_judgement_rules(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "x\n")
        plan = json.loads(self.scan("rules").stdout)
        self.assertEqual([r["id"] for r in plan["files"]["src/a.demo"]], ["demo-structure-001"])

    def test_missing_baseline_is_said(self):
        self.put("src/a.demo", "x\n")
        out = self.hook("gate", session="nobase")
        self.assertEqual(out["decision"], "block")
        self.assertIn("no session baseline", out["systemMessage"])

    def test_degraded_note_surfaced_once(self):
        self.hook("baseline", event="SessionStart")
        d = self.repo / ".git" / "orchid-convention" / "degraded"
        d.mkdir(parents=True, exist_ok=True)
        (d / "demo.lint-missing").write_text("demo: lint did NOT run\n")
        self.assertIn("lint did NOT run", self.hook("gate")["systemMessage"])
        self.assertEqual(self.hook("gate"), {})

    def test_subagents(self):
        self.hook("baseline", event="SessionStart")
        self.put("src/a.demo", "x\n")
        self.assertEqual(self.hook("gate", event="SubagentStop", agent_type="backend-dev"), {})
        env = dict(self.env, CLAUDE_PLUGIN_OPTION_GATED_AGENTS="backend-dev|ios-dev")
        self.assertEqual(self.hook("gate", event="SubagentStop", env=env, agent_type="backend-dev")["decision"],
                         "block")
        env = dict(self.env, CLAUDE_PLUGIN_OPTION_GATED_AGENTS="*")
        self.assertEqual(self.hook("gate", event="SubagentStop", env=env,
                                   agent_type="convention-core:scanner"), {})

    def test_not_a_repo_is_said_once(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        env = dict(self.env, ORCHID_STATE_DIR=str(self.tmp / "st"))
        payload = {"session_id": "s1", "cwd": str(plain), "hook_event_name": "Stop"}
        out = subprocess.run([BASH, str(HOOK), "gate"], input=json.dumps(payload), capture_output=True,
                             text=True, env=env).stdout
        self.assertIn("did not run", json.loads(out)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
