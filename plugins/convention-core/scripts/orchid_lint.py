#!/usr/bin/env python3
"""PostToolUse lint dispatcher: runs each covering pack's declared linter on the whole file.

The write has already happened, so this cannot stop it; it reports. Findings
go back to the agent as a block reason so they are addressed now. The linter
command comes from pack.json as an argument list (never a shell string):
{file} is the written file, and {config_args} expands to the pack's config
arguments when a config is found. The repo's own config, searched upward from
the file to the repo root, wins over the pack's bundled config.

A missing linter is never a silent pass. The first time in a session a stack's
linter is missing (or a stack declares none), the agent and the human are told
that lint did not run, and a note is left for the gate to surface at the end of
the turn. When state cannot be stored, the notice repeats on every write rather
than going quiet.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchid_common as oc  # noqa: E402

MAX_OUTPUT = 4000


def find_config(name: str, file_path: str, root: str, pack_dir: Path):
    d = os.path.dirname(file_path)
    while d:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate):
            return candidate
        if not root or d == root or d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    bundled = pack_dir / name
    return str(bundled) if bundled.is_file() else None


def build_argv(lint: dict, file_path: str, root: str, pack_dir: Path):
    config = lint.get("config")
    config_args = []
    if config:
        found = find_config(config["file"], file_path, root, pack_dir)
        if found:
            config_args = [found if a == "{config}" else a for a in config["args"]]
    argv = [lint["tool"]]
    for a in lint.get("args", []):
        if a == "{config_args}":
            argv.extend(config_args)
        elif a == "{file}":
            argv.append(file_path)
        else:
            argv.append(a)
    return argv


def run(event):
    packs, problems = oc.discover_packs()
    findings, notes = [], list(problems)
    for w in event.writes:
        if not os.path.isfile(w.path):
            continue
        git_root = oc.repo_root(w.path)
        root = git_root or os.path.realpath(event.cwd)
        rel = oc.rel_to(w.path, root)
        state = oc.State(git_root)
        for pack in packs:
            if not pack.covers(rel):
                continue
            lint = pack.lint
            if not lint:
                if state.once(event.session, f"no-linter:{pack.stack}"):
                    notes.append(f"{pack.stack}: the pack declares no linter, so the lint layer does not run "
                                 f"for {pack.stack} files. Treat lint as not tested, not as passed.")
                continue
            tool = lint["tool"]
            note_name = f"{pack.stack}.lint-missing"
            if shutil.which(tool) is None:
                why = (lint.get("missing") or f"{tool} is not on PATH").rstrip()
                if why[-1] not in ".!?":
                    why += "."
                text = (f"{pack.stack}: lint did NOT run: {why} "
                        f"Every {pack.stack} write this session is unlinted; report lint as not tested, "
                        "not as passed.")
                state.note(note_name, text + "\n")
                if state.once(event.session, f"lint-missing:{pack.stack}"):
                    notes.append(text)
                continue
            state.note(note_name, None)
            argv = build_argv(lint, w.path, root, pack.dir)
            timeout = int(lint.get("timeout", 45))
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                      cwd=root or None)
            except subprocess.TimeoutExpired:
                notes.append(f"{pack.stack}: {tool} timed out after {timeout}s on {rel}; lint did not finish, "
                             "which is not a pass.")
                continue
            except OSError as e:
                notes.append(f"{pack.stack}: {tool} could not start ({e}); {rel} was not linted.")
                continue
            output = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if proc.returncode != 0 or output:
                if len(output) > MAX_OUTPUT:
                    output = output[:MAX_OUTPUT] + "\n... (truncated)"
                findings.append(f"{tool} on {rel} (exit {proc.returncode}):\n{output or '(no output)'}")
    return findings, notes


def render_claude(findings, notes):
    out = {}
    ctx = []
    if notes:
        msg = "Orchid convention lint:\n" + "\n".join("- " + n for n in notes)
        out["systemMessage"] = msg
        ctx.append(msg)
    if findings:
        reason = ("The linter reported problems in the file you just wrote. Fix them before moving on.\n\n"
                  + "\n\n".join(findings))
        out["decision"] = "block"
        out["reason"] = reason
    if ctx:
        out["hookSpecificOutput"] = {"hookEventName": "PostToolUse", "additionalContext": "\n\n".join(ctx)}
    return out


def main(argv) -> int:
    host = oc.host_arg(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        findings, notes = run(oc.normalize(payload))
    except Exception as e:  # noqa: BLE001 - a crash must be reported, never read as a pass
        return oc.respond(host, "lint", {"systemMessage": f"Orchid convention lint failed "
                                         f"({type(e).__name__}: {e}); the file was NOT linted."})
    return oc.respond(host, "lint", render_claude(findings, notes))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
