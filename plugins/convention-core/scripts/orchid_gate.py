#!/usr/bin/env python3
"""Stop / SubagentStop gate, and the SessionStart baseline. Python 3.9+ stdlib only.

Usage: orchid_gate.py baseline   (SessionStart: record what the repo looked like)
       orchid_gate.py gate       (Stop or SubagentStop)

The gate passes when the current change set (orchid_scan.py) is empty or has
a seal. Otherwise it blocks the end of the turn with the exact commands that
scan and seal it. Outcomes for a sealed change set:

  clean       pass silently
  standing    pass; a full-repo rule is broken outside this change, said once
  violations  block until fixed and rescanned

Loop discipline: while a scan of this exact hash is in progress the gate
passes without a word. A change set that stays unsealed or unfixed is blocked
twice; on the third stop the gate lets the turn end, says once that the
change is leaving unscanned (or with violations), and records the exit in
state. Repeating the same block forever is a loop, not a gate.

Degraded-capability notes (for example a missing linter) are surfaced here
once per session, because the end of the turn is where a person is looking.
A subagent is gated only when its agent type matches the gated_agents option;
the scanner itself is never gated.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchid_common as oc  # noqa: E402
import orchid_scan as scan  # noqa: E402

ESCALATE_AFTER = 2
SCAN_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orchid_scan.py")


def subagent_gated(payload) -> bool:
    agent = str(payload.get("agent_type") or payload.get("subagent_type") or "")
    if "scanner" in agent:
        return False
    pattern = os.environ.get("CLAUDE_PLUGIN_OPTION_GATED_AGENTS", os.environ.get("ORCHID_GATED_AGENTS", ""))
    if not pattern.strip():
        return False
    if pattern.strip() == "*":
        return True
    try:
        return bool(agent) and re.fullmatch(pattern, agent) is not None
    except re.error:
        return False


def degraded_notes(repo, session):
    out = []
    if not repo.state.available:
        return out
    d = repo.state.dir / "degraded"
    for p in sorted(d.glob("*")) if d.is_dir() else []:
        try:
            text = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text and repo.state.once(session, f"degraded:{p.name}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"):
            out.append(text)
    return out


def strikes(repo, session, digest) -> int:
    def fn(data):
        key = f"{session}:{digest}"
        data[key] = {"n": data.get(key, {}).get("n", 0) + 1, "t": int(time.time())}
        oc._prune(data, 64)
        return data[key]["n"]
    n = repo.state.update("gate-strikes.json", fn)
    return n if n is not None else 1


def record_exit(repo, session, digest, why, files):
    if not repo.state.available:
        return
    line = json.dumps({"time": int(time.time()), "session": session, "hash": digest, "why": why, "files": files})
    try:
        with open(repo.state.dir / "exits.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def instructions(session, digest, files) -> str:
    cmd = f"python3 \"{SCAN_SCRIPT}\" --session {session}"
    shown = "\n".join("  " + f for f in files[:20]) + ("\n  ..." if len(files) > 20 else "")
    return (f"The convention scan has not sealed this change set (hash {digest}, {len(files)} file(s)):\n{shown}\n\n"
            "Spawn the convention-core scanner agent (or follow the convention-detect skill yourself) with "
            f"these commands, run from the repository:\n  {cmd} begin\n  {cmd} rules\n  {cmd} sweep\n"
            f"  {cmd} seal --findings <findings.json>\n"
            "The scanner reports and never edits code. Then stop again.")


def gate(payload) -> dict:
    session = str(payload.get("session_id") or "no-session")
    if payload.get("hook_event_name") == "SubagentStop" and not subagent_gated(payload):
        return {}
    try:
        repo = scan.Repo(str(payload.get("cwd") or os.getcwd()), session)
    except scan.ScanError as e:
        st = oc.State("")
        if st.once(session, "gate-no-repo"):
            return {"systemMessage": f"Orchid convention gate did not run: {e}. Nothing was scanned."}
        return {}
    if not repo.state.available:
        if oc.State("").once(session, "gate-no-state"):
            return {"systemMessage": "Orchid convention gate did not run: no writable state in the git dir, "
                                     "so scans cannot be sealed. This turn ends unscanned."}
        return {}
    messages = list(repo.problems) + degraded_notes(repo, session)
    try:
        entries, warnings = repo.changed()
    except scan.ScanError as e:
        return {"systemMessage": f"Orchid convention gate could not read the change set ({e}); "
                                 "this turn ends unscanned."}
    if warnings and repo.state.once(session, "gate-no-baseline"):
        messages.extend(warnings)
    out = {}
    if entries:
        digest = repo.digest(entries)
        files = [rel for rel, _ in entries]
        seal = repo.read_seal(digest)
        if seal is None:
            current = {}
            if repo.state.available:
                try:
                    current = json.loads((repo.state.dir / "scanning.json").read_text())
                except (OSError, ValueError):
                    current = {}
            in_progress = (current.get("hash") == digest
                           and time.time() - current.get("time", 0) < scan.IN_PROGRESS_SECONDS)
            if not in_progress:
                n = strikes(repo, session, digest)
                if n > ESCALATE_AFTER and repo.state.available:
                    if repo.state.once(session, f"unscanned:{digest}"):
                        messages.append(f"This change set ({digest}, {len(files)} file(s)) is leaving the session "
                                        "UNSCANNED after repeated gate blocks. The exit is recorded; convention "
                                        "results for it are not tested, not passed.")
                        record_exit(repo, session, digest, "unscanned", files)
                else:
                    out = {"decision": "block", "reason": instructions(session, digest, files)}
        elif seal.get("verdict") == "violations":
            bad = [f for f in seal.get("findings", []) if f.get("bucket") == "violation"]
            listing = "\n".join(f"- {f.get('rule')} {f.get('file')}:{f.get('line', '?')} {f.get('evidence', '')}".rstrip()
                                for f in bad[:30])
            n = strikes(repo, session, digest)
            if n > ESCALATE_AFTER and repo.state.available:
                if repo.state.once(session, f"violations:{digest}"):
                    messages.append(f"This change set leaves the session with {len(bad)} sealed convention "
                                    "violation(s) after repeated gate blocks. The exit is recorded.")
                    record_exit(repo, session, digest, "violations", files)
            else:
                out = {"decision": "block",
                       "reason": f"The sealed scan of this change set found {len(bad)} violation(s):\n{listing}\n\n"
                                 "Fix them, then rescan and seal (the hash changes when you edit), and stop again."}
        elif seal.get("verdict") == "standing":
            if repo.state.once(session, f"standing:{digest}"):
                n = sum(1 for f in seal.get("findings", []) if f.get("bucket") == "standing")
                messages.append(f"Convention scan: clean for this change; {n} standing finding(s) in files it "
                                "does not touch (full-repo rules). Reported, not blocking.")
    if messages:
        out["systemMessage"] = "Orchid convention gate:\n" + "\n".join("- " + m for m in messages)
    return out


def main(argv) -> int:
    layer = argv[0] if argv else "gate"
    host = oc.host_arg(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        if layer == "baseline":
            session = str(payload.get("session_id") or "no-session")
            try:
                repo = scan.Repo(str(payload.get("cwd") or os.getcwd()), session)
                repo.record_baseline()
            except scan.ScanError:
                pass
            return 0
        result = gate(payload)
    except Exception as e:  # noqa: BLE001 - a crash must be reported, never read as a pass
        return oc.respond(host, "gate", {"systemMessage": f"Orchid convention gate failed "
                                         f"({type(e).__name__}: {e}); this turn ends unscanned."})
    return oc.respond(host, "gate", result)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
