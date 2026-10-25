"""Tests for the Codex adapter: --host codex output and the .codex/hooks.json template.

Payloads are simulated in the shape assumed in plugins/convention-core/codex/README.md.
These tests pin the translation; they do not prove live Codex behaviour.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "plugins" / "convention-core"
HOOK = CORE / "scripts" / "hook.sh"
TEMPLATE = CORE / "codex" / "hooks.json"
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")

GUARD = {"stack": "demo", "rules": [
    {"id": "demo-naming-001", "pattern": "Foo", "file_glob": "**/*.demo", "severity": "block",
     "overridable": True, "message": "No Foo."},
    {"id": "demo-security-001", "pattern": "SECRET=", "file_glob": "**/*.demo", "severity": "block",
     "overridable": False, "message": "No secrets."},
    {"id": "demo-style-001", "pattern": "TODO", "file_glob": "**/*.demo", "severity": "warn",
     "overridable": True, "message": "Track TODOs."}]}


def patch(*files):
    body = "".join(f"*** Add File: {p}\n" + "".join(f"+{l}\n" for l in text.splitlines()) for p, text in files)
    return "*** Begin Patch\n" + body + "*** End Patch"


class CodexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="orchid-codex-")))
        pack = self.tmp / "packs" / "convention-demo"
        pack.mkdir(parents=True)
        (pack / "pack.json").write_text(json.dumps({"stack": "demo", "files": ["**/*.demo"], "lint": {
            "tool": "fakelint", "args": ["{file}"], "missing": "install fakelint"}}))
        (pack / "guard.json").write_text(json.dumps(GUARD))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        self.env = dict(os.environ, ORCHID_PACKS=str(self.tmp / "packs"), ORCHID_PYTHON=sys.executable,
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env.pop("ORCHID_STATE_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_layer(self, layer, payload, host="codex", command=None):
        argv = command or [BASH, str(HOOK), layer, "--host", host]
        proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=self.env,
                              timeout=60)
        return proc.returncode, proc.stdout.strip(), proc.stderr

    def guard(self, *files, session="c1"):
        return self.run_layer("guard", {"session_id": session, "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                                        "tool_name": "apply_patch",
                                        "tool_input": {"command": ["apply_patch", patch(*files)]}})

    def test_deny_is_exit_2_with_reason_on_stderr(self):
        rc, out, err = self.guard(("src/a.demo", "let Foo = 1\n"))
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("demo-naming-001", err)

    def test_ask_becomes_a_denial_that_hands_over(self):
        for _ in range(2):
            self.assertEqual(self.guard(("src/a.demo", "Foo\n"))[0], 2)
        rc, _, err = self.guard(("src/a.demo", "Foo\n"))
        self.assertEqual(rc, 2)
        self.assertIn("cannot prompt", err)
        self.assertIn("demo-naming-001", err)

    def test_non_overridable_never_hands_over(self):
        for _ in range(4):
            rc, _, err = self.guard(("src/a.demo", "Foo\nSECRET=1\n"))
            self.assertEqual(rc, 2)
            self.assertNotIn("cannot prompt", err)

    def test_warn_is_a_system_message(self):
        rc, out, _ = self.guard(("src/a.demo", "// TODO\n"))
        self.assertEqual(rc, 0)
        self.assertIn("demo-style-001", json.loads(out)["systemMessage"])

    def test_clean_is_silent(self):
        self.assertEqual(self.guard(("src/a.demo", "fine\n"), ("README.md", "Foo\n")), (0, "", ""))

    def test_lint_missing_and_findings(self):
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.demo").write_text("BAD\n")
        payload = {"session_id": "c1", "cwd": str(self.repo), "hook_event_name": "PostToolUse",
                   "tool_name": "apply_patch", "tool_input": {"input": patch(("src/a.demo", "BAD\n"))}}
        rc, out, _ = self.run_layer("lint", payload)
        self.assertEqual(rc, 0)
        self.assertIn("lint did NOT run: install fakelint", json.loads(out)["systemMessage"])
        fake = self.bin / "fakelint"
        fake.write_text("#!/bin/sh\necho \"$1:1: BAD found\"\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        rc, _, err = self.run_layer("lint", payload)
        self.assertEqual(rc, 2)
        self.assertIn("BAD found", err)

    def test_gate_blocks_and_baseline_runs(self):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@e", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-m", "base"], check=True)
        base = {"session_id": "c1", "cwd": str(self.repo)}
        self.assertEqual(self.run_layer("baseline", dict(base, hook_event_name="SessionStart"))[0], 0)
        self.assertEqual(self.run_layer("gate", dict(base, hook_event_name="Stop")), (0, "", ""))
        (self.repo / "a.demo").write_text("x\n")
        rc, _, err = self.run_layer("gate", dict(base, hook_event_name="Stop"))
        self.assertEqual(rc, 2)
        self.assertIn("seal --findings", err)

    def test_unknown_host_says_not_run(self):
        rc, out, _ = self.run_layer("guard", {"tool_input": {}}, host="vim")
        self.assertEqual(rc, 0)
        self.assertIn("did NOT run", json.loads(out)["systemMessage"])

    def test_template_commands_run(self):
        data = json.loads(TEMPLATE.read_text())
        self.assertEqual(set(data["hooks"]), {"SessionStart", "PreToolUse", "PostToolUse", "Stop"})
        commands = {}
        for event, groups in data["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    self.assertIn("--host codex", h["command"])
                    commands[event] = h["command"].replace("__ORCHID_CORE__", str(CORE))
        self.assertIn("apply_patch", data["hooks"]["PreToolUse"][0]["matcher"])
        payload = {"session_id": "c1", "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                   "tool_name": "apply_patch", "tool_input": {"command": ["apply_patch", patch(("a.demo", "Foo\n"))]}}
        rc, _, err = self.run_layer(None, payload, command=["sh", "-c", commands["PreToolUse"]])
        self.assertEqual(rc, 2, err)
        self.assertIn("demo-naming-001", err)


if __name__ == "__main__":
    unittest.main()
