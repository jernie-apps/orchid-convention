"""Behaviour tests for the generic guard engine (hook.sh guard).

Every test drives the real entry point with a host-shaped payload against a
throwaway pack and a throwaway git repo, so input normalization, pack
discovery, glob matching, repo overrides, the strike counter and the output
contract are all exercised together. These are simulated payloads: they prove
the engine's contract, not live Claude Code or Codex behaviour.
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
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")

GUARD = {"stack": "demo", "rules": [
    {"id": "demo-naming-001", "pattern": "(^|[^A-Za-z0-9_])Foo([^A-Za-z0-9_]|$)", "file_glob": "**/*.demo",
     "severity": "block", "overridable": True, "message": "Do not name things Foo."},
    {"id": "demo-security-001", "pattern": "secret[[:space:]]*=[[:space:]]*\"", "flags": "i",
     "file_glob": "**/*.demo", "exclude_glob": "**/Mock/**", "exclude_pattern": "^[[:space:]]*//",
     "severity": "block", "overridable": False, "message": "No hardcoded secrets."},
    {"id": "demo-layering-001", "pattern": "^import UI", "file_glob": "**/Domain/**/*.demo",
     "severity": "block", "overridable": True, "message": "Domain must not import UI."},
    {"id": "demo-style-001", "pattern": "TODO", "file_glob": "**/*.demo",
     "severity": "warn", "overridable": True, "message": "Track TODOs in the issue tracker."},
]}
PACK = {"stack": "demo", "files": ["**/*.demo"], "exclude": ["**/generated/**"], "lint": None}


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd)] + list(args), check=True, capture_output=True)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orchid-guard-"))
        self.pack = self.tmp / "packs" / "convention-demo"
        self.pack.mkdir(parents=True)
        (self.pack / "pack.json").write_text(json.dumps(PACK))
        (self.pack / "guard.json").write_text(json.dumps(GUARD))
        self.repo = (self.tmp / "repo")
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        self.repo = Path(os.path.realpath(self.repo))
        self.env = dict(os.environ, ORCHID_PACKS=str(self.tmp / "packs"), ORCHID_PYTHON=sys.executable)
        self.env.pop("ORCHID_STATE_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, payload, env=None):
        proc = subprocess.run([BASH, str(HOOK), "guard"], input=json.dumps(payload), capture_output=True,
                              text=True, env=env or self.env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def write(self, path, content, session="s1", tool="Write"):
        ti = {"file_path": str(self.repo / path)}
        if tool == "Write":
            ti["content"] = content
        elif tool == "Edit":
            ti.update(old_string="x", new_string=content)
        else:
            ti["edits"] = [{"old_string": "a", "new_string": c} for c in content]
        return self.run_hook({"session_id": session, "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                              "tool_name": tool, "tool_input": ti})

    @staticmethod
    def decision(out):
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    @staticmethod
    def reason(out):
        h = out.get("hookSpecificOutput", {})
        return h.get("permissionDecisionReason") or h.get("additionalContext") or ""

    def test_clean_write_is_silent(self):
        self.assertEqual(self.write("src/a.demo", "let bar = 1\n"), {})

    def test_uncovered_file_is_silent(self):
        self.assertEqual(self.write("src/a.txt", "let Foo = 1\n"), {})
        self.assertEqual(self.write("src/generated/a.demo", "let Foo = 1\n"), {})

    def test_reports_every_rule_nonoverridable_first(self):
        out = self.write("src/Domain/a.demo", "import UIKit\nlet Foo = 1\nlet secret = \"x\"\n// TODO\n")
        self.assertEqual(self.decision(out), "deny")
        r = self.reason(out)
        for rid in ("demo-naming-001", "demo-security-001", "demo-layering-001", "demo-style-001"):
            self.assertIn(rid, r)
        self.assertLess(r.index("demo-security-001"), r.index("demo-layering-001"))
        self.assertLess(r.index("demo-security-001"), r.index("demo-naming-001"))
        self.assertIn("NON-OVERRIDABLE demo-security-001 (line 3)", r)
        self.assertIn("Also, non-blocking", r)

    def test_two_strikes_then_ask_then_clean_resets(self):
        decisions = [self.decision(self.write("src/a.demo", "let Foo = 1\n")) for _ in range(4)]
        self.assertEqual(decisions, ["deny", "deny", "ask", "ask"])
        self.assertEqual(self.write("src/a.demo", "let bar = 1\n"), {})
        self.assertEqual(self.decision(self.write("src/a.demo", "let Foo = 1\n")), "deny")

    def test_strikes_are_per_file_and_session(self):
        for _ in range(2):
            self.write("src/a.demo", "let Foo = 1\n")
        self.assertEqual(self.decision(self.write("src/b.demo", "let Foo = 1\n")), "deny")
        self.assertEqual(self.decision(self.write("src/a.demo", "let Foo = 1\n", session="s2")), "deny")
        self.assertEqual(self.decision(self.write("src/a.demo", "let Foo = 1\n")), "ask")

    def test_nonoverridable_never_escalates(self):
        for _ in range(6):
            out = self.write("src/a.demo", "let Foo = 1\nlet secret = \"x\"\n")
            self.assertEqual(self.decision(out), "deny")

    def test_state_lives_in_git_dir_not_work_tree(self):
        self.write("src/a.demo", "let Foo = 1\n")
        self.assertTrue((self.repo / ".git" / "orchid-convention" / "guard-strikes.json").exists())
        status = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")

    def test_warn_only_gives_context_without_decision(self):
        out = self.write("src/a.demo", "// TODO later\n")
        self.assertIsNone(self.decision(out))
        self.assertIn("demo-style-001", out["hookSpecificOutput"]["additionalContext"])

    def test_exclusions(self):
        self.assertEqual(self.write("src/a.demo", "// let secret = \"x\"\n"), {})
        self.assertEqual(self.write("src/Mock/a.demo", "let secret = \"x\"\n"), {})
        self.assertEqual(self.decision(self.write("src/a.demo", "// secret = \"x\"\nsecret = \"y\"\n")), "deny")

    def test_edit_and_multiedit_fragments(self):
        out = self.write("src/a.demo", "let Foo = 1\n", tool="Edit")
        self.assertIn("inserted line 1", self.reason(out))
        out = self.write("src/b.demo", ["let ok = 1", "let Foo = 2"], tool="MultiEdit")
        self.assertEqual(self.decision(out), "deny")

    def test_repo_override_skips_overridable_and_refuses_nonoverridable(self):
        conv = self.repo / ".orchid" / "conventions"
        conv.mkdir(parents=True)
        (conv / "demo.md").write_text(
            "# Overrides\n\n## demo-naming-001\noverride: global\nreason: legacy API names\n\n"
            "### `demo-security-001`\noverride: global\nreason: please\n\n"
            "## demo-layering-001\noverride: global\n")
        self.assertEqual(self.write("src/a.demo", "let Foo = 1\n"), {})
        out = self.write("src/Domain/a.demo", "import UIKit\nlet secret = \"x\"\n")
        r = self.reason(out)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("demo-layering-001", r, "an override without a reason must not be honoured")
        self.assertIn("is not honoured", r)

    def test_codex_apply_patch_multi_file(self):
        patch = ("*** Begin Patch\n*** Add File: src/b.demo\n+let Foo = 2\n"
                 "*** Update File: src/c.demo\n@@\n-old\n+let secret = \"y\"\n"
                 "*** Delete File: src/d.demo\n*** End Patch")
        out = self.run_hook({"session_id": "c1", "cwd": str(self.repo), "hook_event_name": "PreToolUse",
                             "tool_name": "apply_patch", "tool_input": {"command": ["apply_patch", patch]}})
        r = self.reason(out)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("src/b.demo breaks 1", r)
        self.assertIn("src/c.demo breaks 1", r)
        self.assertIn("NON-OVERRIDABLE demo-security-001 (inserted line 1)", r)

    def test_broken_pattern_is_reported_not_passed(self):
        guard = json.loads(json.dumps(GUARD))
        guard["rules"][0]["pattern"] = "Foo("
        (self.pack / "guard.json").write_text(json.dumps(guard))
        out = self.write("src/a.demo", "let Foo = 1\n")
        self.assertIn("demo-naming-001: pattern could not be evaluated", out.get("systemMessage", ""))

    def test_missing_overridable_field_is_reported(self):
        guard = json.loads(json.dumps(GUARD))
        del guard["rules"][1]["overridable"]
        (self.pack / "guard.json").write_text(json.dumps(guard))
        out = self.write("src/a.demo", "let secret = \"x\"\n")
        self.assertIn("demo-security-001: guard.json entry lacks 'overridable'", out.get("systemMessage", ""))

    def test_no_state_means_no_escalation_and_says_so(self):
        plain = Path(tempfile.mkdtemp(prefix="orchid-nogit-", dir=self.tmp))
        payload = {"session_id": "s1", "cwd": str(plain), "tool_name": "Write",
                   "tool_input": {"file_path": str(plain / "a.demo"), "content": "let Foo = 1\n"}}
        for _ in range(4):
            out = self.run_hook(payload)
            self.assertEqual(self.decision(out), "deny")
        self.assertIn("strike counter unavailable", out.get("systemMessage", ""))

    def test_no_packs_is_said_once(self):
        env = dict(self.env, ORCHID_PACKS=str(self.tmp / "empty"))
        out = self.run_hook({"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
                             "tool_input": {"file_path": str(self.repo / "a.demo"), "content": "x"}}, env)
        self.assertIn("found no stack pack", out.get("systemMessage", ""))
        again = self.run_hook({"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
                               "tool_input": {"file_path": str(self.repo / "a.demo"), "content": "x"}}, env)
        self.assertEqual(again, {})

    def test_garbage_input_is_reported(self):
        proc = subprocess.run([BASH, str(HOOK), "guard"], input="not json", capture_output=True, text=True,
                              env=self.env)
        self.assertIn("was NOT checked", json.loads(proc.stdout)["systemMessage"])

    def test_missing_python_is_reported(self):
        env = dict(self.env, ORCHID_PYTHON="no-such-python3")
        proc = subprocess.run([BASH, str(HOOK), "guard"], input="{}", capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("did not run", json.loads(proc.stdout)["systemMessage"])

    def test_fixture_runner_on_demo_pack(self):
        fx = self.pack / "fixtures"
        fx.mkdir()
        (fx / "demo-security-001.cases").write_text(
            "#> case good: env\n#> path: src/a.demo\nlet secret = env()\n"
            "#> case bad: literal plus Foo\n#> path: src/Domain/a.demo\n"
            "#> expect: demo-security-001 demo-naming-001 demo-layering-001 demo-model-001\n"
            "import UI\nlet Foo = 1\nlet secret = \"x\"\n"
            "#> case bad: as an edit\n#> path: src/a.demo\n#> tool: Edit\n#> expect: demo-style-001\n// TODO\n")
        run = subprocess.run([sys.executable, str(SCRIPTS / "run_fixtures.py"), str(self.pack)],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("lint or scanner layer, not asserted here: demo-model-001", run.stdout)
        self.assertIn("[codex]", run.stdout)
        self.assertIn("lint none", run.stdout)
        # A fixture that claims a rule the guard does not report must fail the run.
        (fx / "demo-security-001.cases").write_text(
            "#> case bad: wrong claim\n#> path: src/a.demo\n#> expect: demo-naming-001\nlet bar = 1\n")
        run = subprocess.run([sys.executable, str(SCRIPTS / "run_fixtures.py"), str(self.pack)],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("missing ['demo-naming-001']", run.stdout)


if __name__ == "__main__":
    unittest.main()
