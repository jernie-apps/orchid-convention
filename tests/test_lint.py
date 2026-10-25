"""Behaviour tests for the lint dispatcher (hook.sh lint).

A fake linter on a temporary PATH stands in for the pack's real one, so these
prove the dispatch contract (argv building, config precedence, reporting, the
missing-linter notice), not any real linter's behaviour.
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
HOOK = REPO / "plugins" / "convention-core" / "scripts" / "hook.sh"
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")

FAKE = """#!/bin/sh
# Records its argv, then complains about any line containing BAD.
printf '%s\\n' "$@" > "$FAKE_LOG"
for last in "$@"; do :; done
if grep -n BAD "$last" >/dev/null 2>&1; then
  grep -n BAD "$last" | sed 's/^/warning: /'
  exit 2
fi
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
exit 0
"""


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="orchid-lint-")))
        self.pack = self.tmp / "packs" / "convention-demo"
        self.pack.mkdir(parents=True)
        self.set_pack({"tool": "fakelint", "args": ["check", "{config_args}", "{file}"],
                       "config": {"file": "fake.cfg", "args": ["--config", "{config}"]},
                       "missing": "install fakelint with `brew install fakelint`", "timeout": 5})
        (self.pack / "fake.cfg").write_text("bundled\n")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.repo = self.tmp / "repo"
        (self.repo / "src" / "deep").mkdir(parents=True)
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        self.log = self.tmp / "argv.log"
        self.env = dict(os.environ, ORCHID_PACKS=str(self.tmp / "packs"), ORCHID_PYTHON=sys.executable,
                        FAKE_LOG=str(self.log), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env.pop("ORCHID_STATE_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_pack(self, lint):
        (self.pack / "pack.json").write_text(json.dumps({"stack": "demo", "files": ["**/*.demo"], "lint": lint}))

    def install_fake(self):
        f = self.bin / "fakelint"
        f.write_text(FAKE)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    def lint(self, rel, content, session="s1", env=None):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        data = {"session_id": session, "cwd": str(self.repo), "hook_event_name": "PostToolUse",
                "tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}
        proc = subprocess.run([BASH, str(HOOK), "lint"], input=json.dumps(data), capture_output=True,
                              text=True, env=env or self.env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_missing_linter_said_once_per_session_and_noted(self):
        out = self.lint("src/a.demo", "ok\n")
        self.assertIn("lint did NOT run: install fakelint", out["systemMessage"])
        self.assertIn("not as passed", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.lint("src/b.demo", "ok\n"), {})
        self.assertIn("did NOT run", self.lint("src/a.demo", "ok\n", session="s2")["systemMessage"])
        note = self.repo / ".git" / "orchid-convention" / "degraded" / "demo.lint-missing"
        self.assertTrue(note.exists())
        self.install_fake()
        self.assertEqual(self.lint("src/a.demo", "ok\n"), {})
        self.assertFalse(note.exists(), "the note must clear once the linter is present")

    def test_findings_block_with_output(self):
        self.install_fake()
        out = self.lint("src/a.demo", "fine\nBAD line\n")
        self.assertEqual(out["decision"], "block")
        self.assertIn("fakelint on src/a.demo (exit 2)", out["reason"])
        self.assertIn("warning: 2:BAD line", out["reason"])

    def test_clean_is_silent_and_argv_is_exact(self):
        self.install_fake()
        self.assertEqual(self.lint("src/a.demo", "fine\n"), {})
        argv = self.log.read_text().splitlines()
        self.assertEqual(argv, ["check", "--config", str(self.pack / "fake.cfg"), str(self.repo / "src/a.demo")])

    def test_repo_config_wins_over_bundled(self):
        self.install_fake()
        (self.repo / "src" / "fake.cfg").write_text("repo\n")
        self.lint("src/deep/a.demo", "fine\n")
        self.assertIn(str(self.repo / "src" / "fake.cfg"), self.log.read_text().splitlines())

    def test_no_config_drops_config_args(self):
        self.install_fake()
        (self.pack / "fake.cfg").unlink()
        self.lint("src/a.demo", "fine\n")
        self.assertEqual(self.log.read_text().splitlines(), ["check", str(self.repo / "src/a.demo")])

    def test_file_name_is_one_argument(self):
        self.install_fake()
        self.lint("src/odd name; rm -rf x.demo", "fine\n")
        self.assertEqual(self.log.read_text().splitlines()[-1], str(self.repo / "src/odd name; rm -rf x.demo"))

    def test_timeout_is_not_a_pass(self):
        self.install_fake()
        self.set_pack({"tool": "fakelint", "args": ["{file}"], "missing": "x", "timeout": 1})
        out = self.lint("src/a.demo", "fine\n", env=dict(self.env, FAKE_SLEEP="3"))
        self.assertIn("timed out", out["systemMessage"])

    def test_pack_without_linter_says_so_once(self):
        self.set_pack(None)
        self.assertIn("declares no linter", self.lint("src/a.demo", "x\n")["systemMessage"])
        self.assertEqual(self.lint("src/a.demo", "x\n"), {})

    def test_uncovered_file_is_silent(self):
        self.assertEqual(self.lint("src/a.txt", "BAD\n"), {})


if __name__ == "__main__":
    unittest.main()
