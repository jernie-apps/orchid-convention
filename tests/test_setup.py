"""Behaviour tests for orchid_setup.py (detect, init, override, health), run against the real Swift pack."""
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
CORE = REPO / "plugins" / "convention-core"
SETUP = CORE / "scripts" / "orchid_setup.py"
HOOK = CORE / "scripts" / "hook.sh"
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="orchid-setup-")))
        self.repo = self.tmp / "app"
        (self.repo / "Sources" / "App").mkdir(parents=True)
        (self.repo / "Sources" / "App" / "Main.swift").write_text("print(1)\n")
        (self.repo / "AGENTS.md").write_text("# App\n\nExisting instructions.\n")
        os.symlink("AGENTS.md", self.repo / "CLAUDE.md")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "init")
        self.env = dict(os.environ, ORCHID_PACKS=str(REPO / "plugins" / "convention-swift"),
                        ORCHID_PYTHON=sys.executable)
        self.env.pop("ORCHID_STATE_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo)] + list(args), check=True, capture_output=True)

    def setup_cmd(self, *args):
        return subprocess.run([sys.executable, str(SETUP)] + list(args), cwd=self.repo, capture_output=True,
                              text=True, env=self.env, timeout=60)

    def ok(self, *args):
        proc = self.setup_cmd(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_detect_writes_nothing(self):
        out = self.ok("detect")
        self.assertEqual(out["stacks"]["swift"]["files"], 1)
        self.assertFalse(out["stacks"]["swift"]["repo_tier"])
        self.assertEqual(self.git_status(), "")

    def git_status(self):
        return subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True,
                              text=True).stdout

    def test_init_is_idempotent_and_edits_agents_through_symlink(self):
        first = self.ok("init", "--stacks", "swift")
        self.assertIn(".orchid/conventions/swift.md", first["written"])
        agents = (self.repo / "AGENTS.md").read_text()
        self.assertTrue(agents.startswith("# App\n\nExisting instructions.\n"))
        self.assertEqual(agents.count("orchid-convention:begin"), 1)
        self.assertTrue((self.repo / "CLAUDE.md").is_symlink())
        (self.repo / ".orchid/conventions/swift.md").write_text("custom\n")
        self.ok("init", "--stacks", "swift")
        self.assertEqual((self.repo / "AGENTS.md").read_text(), agents)
        self.assertEqual((self.repo / ".orchid/conventions/swift.md").read_text(), "custom\n")

    def test_init_rejects_unknown_stack(self):
        proc = self.setup_cmd("init", "--stacks", "cobol")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("no installed pack for: cobol", proc.stderr)

    def test_codex_hooks_installed_and_merged(self):
        codex = self.repo / ".codex"
        codex.mkdir()
        (codex / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "shell", "hooks": [{"type": "command", "command": "echo mine"}]}]}}))
        self.ok("init", "--stacks", "swift", "--codex")
        self.ok("init", "--stacks", "swift", "--codex")
        data = json.loads((codex / "hooks.json").read_text())
        commands = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertIn("echo mine", commands)
        ours = [c for c in commands if "hook.sh" in c]
        self.assertEqual(len(ours), 1, "re-running must not duplicate entries")
        self.assertIn(str(CORE), ours[0])
        self.assertNotIn("__ORCHID_CORE__", (codex / "hooks.json").read_text())

    def test_override_recorded_and_honoured_by_guard(self):
        out = self.ok("override", "swift-naming-001", "Protocol", "names", "come", "from", "a", "generated", "SDK")
        self.assertEqual(out["file"], ".orchid/conventions/swift.md")
        self.ok("override", "swift-naming-001", "Generated SDK names")
        text = (self.repo / ".orchid/conventions/swift.md").read_text()
        self.assertEqual(text.count("## swift-naming-001"), 1)
        self.assertIn("reason: Generated SDK names", text)
        payload = {"session_id": "s", "cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": str(self.repo / "Sources/App/S.swift"),
                                  "content": "protocol IUserStore {}\n"}}
        proc = subprocess.run([BASH, str(HOOK), "guard"], input=json.dumps(payload), capture_output=True,
                              text=True, env=self.env)
        self.assertEqual(proc.stdout.strip(), "")

    def test_override_refuses_non_overridable_and_empty_reason(self):
        proc = self.setup_cmd("override", "swift-security-001", "we need it")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("non-overridable", proc.stderr)
        self.assertFalse((self.repo / ".orchid/conventions/swift.md").exists())
        self.assertEqual(self.setup_cmd("override", "swift-naming-001", "  ").returncode, 1)
        self.assertEqual(self.setup_cmd("override", "swift-naming-999", "x").returncode, 1)

    def test_health_reports_overrides_strikes_and_refusals(self):
        self.ok("override", "swift-naming-001", "Generated SDK names")
        conv = self.repo / ".orchid/conventions/swift.md"
        conv.write_text(conv.read_text() + "\n## swift-security-001\noverride: global\nreason: please\n")
        payload = {"session_id": "s", "cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": str(self.repo / "Sources/App/V.swift"),
                                  "content": "struct LoginViewModel {}\n"}}
        subprocess.run([BASH, str(HOOK), "guard"], input=json.dumps(payload), capture_output=True, text=True,
                       env=self.env)
        report = self.ok("health")
        swift = report["stacks"]["swift"]
        self.assertEqual(swift["rules"], 14)
        self.assertEqual(swift["layers"], {"guard": 11, "lint": 1, "scanner": 2, "sweep-only": 0})
        self.assertIn("swift-naming-001", swift["overrides"])
        self.assertEqual(swift["refused_overrides"], ["swift-security-001"])
        self.assertEqual(swift["guard_strikes"], {"swift-structure-001": 1})

    def test_outside_git_exits_2(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        proc = subprocess.run([sys.executable, str(SETUP), "detect"], cwd=plain, capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
