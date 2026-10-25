#!/usr/bin/env python3
"""Replay every pack's fixture cases through the real hook entry point.

Usage: run_fixtures.py [<pack-dir> ...]     (default: every plugins/convention-*/pack.json)

Each case in fixtures/<id>.cases is sent to `hook.sh guard` twice: as a
Claude Code Write/Edit payload with --host claude, and as a Codex apply_patch
payload with --host codex (whose exit status and stderr are mapped back).
Both must give the same verdict:

  good   no denial, no prompt, no rule mentioned, no engine note.
  bad    exactly the guarded rules in '#> expect' are reported (none missing,
         none extra); any blocking one means deny, warn-only means context
         without a decision; non-overridable rules are listed first. Expected
         rules that guard.json does not hold are the scanner's to judge: the
         guard must stay silent about them, and they are listed as not
         asserted here.

Then the lint layer is driven once per pack. When the pack's linter is not on
PATH, the first write must say so with the pack's own message and the second
must stay quiet; that is checked, and printed as "lint missing", never as a
pass. When the linter is present, each case file is linted and the result
count is printed for information only.

Exit 0 when every assertion holds, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HOOK = HERE / "hook.sh"
sys.path.insert(0, str(HERE))
import validate_rules as vr  # noqa: E402

ID_RE = re.compile(r"[a-z][a-z0-9]*-[a-z]+-[0-9]{3}")
BASH = os.environ.get("ORCHID_TEST_BASH", "bash")


def payload(shape: str, case: dict, cwd: str, session: str) -> dict:
    path = case["path"]
    body = case["body"]
    if shape == "claude":
        if case["tool"] == "Edit":
            ti = {"file_path": os.path.join(cwd, path), "old_string": "", "new_string": body}
        else:
            ti = {"file_path": os.path.join(cwd, path), "content": body}
        return {"session_id": session, "cwd": cwd, "hook_event_name": "PreToolUse",
                "tool_name": case["tool"], "tool_input": ti}
    plus = "\n".join("+" + line for line in body.rstrip("\n").split("\n"))
    if case["tool"] == "Edit":
        patch = f"*** Begin Patch\n*** Update File: {path}\n@@\n{plus}\n*** End Patch"
    else:
        patch = f"*** Begin Patch\n*** Add File: {path}\n{plus}\n*** End Patch"
    return {"session_id": session, "cwd": cwd, "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch", "tool_input": {"command": ["apply_patch", patch]}}


def call(layer: str, data: dict, env: dict, host: str = "claude") -> dict:
    """Run one layer and return its result in Claude Code's output shape.

    A Codex run (--host codex) is mapped back: exit status 2 with stderr is a
    denial, a stdout systemMessage is context, unless it is an engine note.
    """
    proc = subprocess.run([BASH, str(HOOK), layer, "--host", host], input=json.dumps(data), capture_output=True,
                          text=True, env=env, timeout=60)
    out = proc.stdout.strip()
    if host == "codex":
        if proc.returncode == 2:
            return {"hookSpecificOutput": {"permissionDecision": "deny",
                                           "permissionDecisionReason": proc.stderr}}
        if proc.returncode != 0:
            raise RuntimeError(f"hook.sh {layer} exited {proc.returncode}: {proc.stderr.strip()}")
        msg = json.loads(out).get("systemMessage", "") if out else ""
        if "could not check" in msg or "did NOT run" in msg or "failed" in msg:
            return {"systemMessage": msg}
        return {"hookSpecificOutput": {"additionalContext": msg}} if msg else {}
    if proc.returncode != 0:
        raise RuntimeError(f"hook.sh {layer} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(out) if out else {}


class Runner:
    def __init__(self):
        self.failures = 0

    def fail(self, msg: str, out=None):
        self.failures += 1
        print(f"FAIL: {msg}")
        if out is not None:
            print("  output: " + json.dumps(out))

    def run_pack(self, pack_dir: Path):
        pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
        guard = json.loads((pack_dir / "guard.json").read_text(encoding="utf-8")) \
            if (pack_dir / "guard.json").exists() else {"rules": []}
        rules = {r["id"]: r for r in guard["rules"]}
        work = Path(tempfile.mkdtemp(prefix="orchid-fixtures-"))
        env = dict(os.environ, ORCHID_PACKS=str(pack_dir))
        try:
            files = sorted((pack_dir / "fixtures").glob("*.cases"))
            if not files:
                self.fail(f"{pack_dir}: no fixtures")
            n = 0
            for f in files:
                for i, case in enumerate(vr.parse_cases(f.read_text(encoding="utf-8"), str(f))):
                    for shape in ("claude", "codex"):
                        n += 1
                        repo = work / f"r{n}"
                        repo.mkdir()
                        env["ORCHID_STATE_DIR"] = str(work / f"s{n}")
                        out = call("guard", payload(shape, case, os.path.realpath(repo), f"fx{n}"), env, shape)
                        self.check(f"{f.name}:{case['line']} [{shape}] {case['kind']}: {case['title']}",
                                   case, rules, out)
            self.check_lint(pack, pack_dir, files, work, env)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def check(self, label: str, case: dict, rules: dict, out: dict):
        hso = out.get("hookSpecificOutput", {})
        decision = hso.get("permissionDecision")
        text = hso.get("permissionDecisionReason") or hso.get("additionalContext") or ""
        mentioned = set(ID_RE.findall(text)) & set(rules)
        if "systemMessage" in out:
            self.fail(f"{label}: engine reported it could not check everything", out)
            return
        if case["kind"] == "good":
            if decision or mentioned:
                self.fail(f"{label}: expected a clean pass", out)
            else:
                print(f"ok: {label}")
            return
        guarded = [r for r in case["expect"] if r in rules]
        scanner = [r for r in case["expect"] if r not in rules]
        note = f" (lint or scanner layer, not asserted here: {' '.join(scanner)})" if scanner else ""
        if not guarded:
            if out:
                self.fail(f"{label}: guard must stay silent for rules it does not hold", out)
            else:
                print(f"ok: {label}: guard silent{note}")
            return
        if mentioned != set(guarded):
            missing = sorted(set(guarded) - mentioned)
            extra = sorted(mentioned - set(guarded))
            self.fail(f"{label}: missing {missing}, unexpected {extra}", out)
            return
        blocking = [r for r in guarded if rules[r]["severity"] == "block"]
        want = "deny" if blocking else None
        if decision != want:
            self.fail(f"{label}: decision {decision!r}, expected {want!r}", out)
            return
        nonneg = [text.find(r) for r in guarded if rules[r]["overridable"] is False and r in blocking]
        ordinary = [text.find(r) for r in guarded if rules[r]["overridable"] is True and r in blocking]
        if nonneg and ordinary and max(nonneg) > min(ordinary):
            self.fail(f"{label}: non-overridable rules must be listed first", out)
            return
        print(f"ok: {label}: {decision or 'context'} {' '.join(guarded)}{note}")

    def check_lint(self, pack: dict, pack_dir: Path, files, work: Path, env: dict):
        lint = pack.get("lint")
        stack = pack["stack"]
        cases = [c for f in files for c in vr.parse_cases(f.read_text(encoding="utf-8"), str(f))]
        if not cases:
            return
        repo = work / "lint"
        repo.mkdir()
        env = dict(env, ORCHID_STATE_DIR=str(work / "lint-state"))

        def write_and_lint(case, session):
            target = repo / case["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(case["body"], encoding="utf-8")
            data = {"session_id": session, "cwd": str(repo.resolve()), "hook_event_name": "PostToolUse",
                    "tool_name": "Write", "tool_input": {"file_path": str(target.resolve()),
                                                         "content": case["body"]}}
            return call("lint", data, env)

        if not lint:
            out = write_and_lint(cases[0], "lint1")
            if "declares no linter" not in out.get("systemMessage", ""):
                self.fail(f"{stack}: a pack without a linter must say lint does not run", out)
            else:
                print(f"lint none: {stack} declares no linter, and the session is told so")
            return
        if shutil.which(lint["tool"], path=env.get("PATH")) is None:
            first = write_and_lint(cases[0], "lint1")
            second = write_and_lint(cases[0], "lint1")
            msg = first.get("systemMessage", "")
            if "did NOT run" not in msg or lint["missing"] not in msg:
                self.fail(f"{stack}: missing {lint['tool']} must be reported with the pack's message", first)
            elif second:
                self.fail(f"{stack}: the missing-linter notice must appear once per session", second)
            else:
                print(f"lint missing: {lint['tool']} is not on PATH; reported once per session "
                      "(lint layer NOT exercised on this host)")
            return
        reported = 0
        for i, case in enumerate(cases):
            out = write_and_lint(case, f"lint{i}")
            reported += 1 if out.get("decision") == "block" else 0
        print(f"lint ran: {lint['tool']} on {len(cases)} case file(s), {reported} reported findings "
              "(informational, not asserted)")


def main(argv) -> int:
    dirs = [Path(a).resolve() for a in argv] or sorted(
        p.parent for p in (REPO / "plugins").glob("convention-*/pack.json"))
    if not dirs:
        print("no packs found; nothing was replayed")
        return 0
    runner = Runner()
    for d in dirs:
        print(f"== {d.name}")
        runner.run_pack(d)
    if runner.failures:
        print(f"FAILED: {runner.failures} fixture assertion(s).")
        return 1
    print(f"OK: fixtures replayed for {len(dirs)} pack(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
