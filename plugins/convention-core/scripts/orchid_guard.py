#!/usr/bin/env python3
"""PreToolUse guard: one engine for every stack, driven by each pack's guard.json.

Reads a Claude Code or Codex hook payload on stdin. For every file the call
writes, it picks the packs whose pack.json globs cover the path and runs their
guard rules over the new text (a whole write, or only the inserted lines of an
edit). Patterns are matched per line by grep -E, the same matcher the
validator uses, so a rule cannot pass validation and behave differently here.

Decision:
  * Every broken rule is reported in one response; non-overridable rules first.
  * Blocking hits deny. Strikes are counted per (session, file, rule): after
    two denials, the third attempt asks the human instead of denying again.
  * A non-overridable rule never escalates: any hit on one denies, whatever
    the count. Escalating it would let a prompt approve a hardcoded secret.
  * A write with no blocking hit clears that file's strikes for the session.
  * Warn-severity hits ride along as context and never block.
  * A repo override in .orchid/conventions/<stack>.md skips an overridable
    rule and is refused, with a note, for a non-overridable one.
  * Anything the engine could not evaluate is reported, never read as a pass.

Exit status is always 0; the decision is in the JSON on stdout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchid_common as oc  # noqa: E402

ESCALATE_AFTER = 2
STRIKES = "guard-strikes.json"


def grep_lines(pattern: str, text: str, icase: bool):
    args = ["grep", "-n", "-E"] + (["-i"] if icase else []) + ["--", pattern]
    proc = subprocess.run(args, input=text, capture_output=True, text=True, timeout=5)
    if proc.returncode == 1:
        return set()
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or f"grep exit {proc.returncode}")
    return {int(x.split(":", 1)[0]) for x in proc.stdout.splitlines() if x}


def evaluate(pack, rel: str, text: str, overrides: dict):
    """Return (findings, notes) for one pack over one file's new text."""
    findings, notes = [], []
    for rule in pack.guard_rules():
        rid = rule.get("id", "?")
        try:
            if not oc.glob_match(rule["file_glob"], rel):
                continue
            if rule.get("exclude_glob") and oc.glob_match(rule["exclude_glob"], rel):
                continue
            overridable = rule["overridable"]
            if not isinstance(overridable, bool):
                raise KeyError("overridable")
            if rid in overrides and overridable:
                continue
            icase = "i" in rule.get("flags", "")
            hits = grep_lines(rule["pattern"], text, icase)
            if hits and rule.get("exclude_pattern"):
                hits -= grep_lines(rule["exclude_pattern"], text, icase)
        except KeyError as e:
            notes.append(f"{rid}: guard.json entry lacks {e}; the rule was not checked")
            continue
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            notes.append(f"{rid}: pattern could not be evaluated ({e}); the rule was not checked")
            continue
        if not hits:
            continue
        refused = rid in overrides and not overridable
        findings.append({
            "id": rid,
            "stack": pack.stack,
            "severity": "block" if rule.get("severity", "block") == "block" else "warn",
            "overridable": overridable,
            "message": rule.get("message", ""),
            "lines": sorted(hits),
            "override_refused": refused,
        })
    return findings, notes


def bump_strikes(state, session: str, path: str, ids):
    def fn(data):
        sess = data.setdefault(session, {"t": 0, "files": {}})
        sess["t"] = int(time.time())
        counts = sess["files"].setdefault(path, {})
        for rid in ids:
            counts[rid] = counts.get(rid, 0) + 1
        oc._prune(data)
        return {rid: counts[rid] for rid in ids}
    return state.update(STRIKES, fn)


def clear_strikes(state, session: str, path: str):
    def fn(data):
        sess = data.get(session)
        if isinstance(sess, dict):
            sess.get("files", {}).pop(path, None)
    state.update(STRIKES, fn)


def describe(f: dict, whole: bool) -> str:
    where = "line" if whole else "inserted line"
    lines = ", ".join(str(n) for n in f["lines"][:5]) + (" ..." if len(f["lines"]) > 5 else "")
    tag = "NON-OVERRIDABLE " if not f["overridable"] else ""
    out = f"- {tag}{f['id']} ({where} {lines}): {f['message']}"
    if f["override_refused"]:
        out += (f" The repo override in .orchid/conventions/{f['stack']}.md is not honoured:"
                " this rule cannot be overridden.")
    return out


def decide(event):
    packs, problems = oc.discover_packs()
    notes = list(problems)
    blocks, warns, max_strike, nonneg = [], [], 0, False
    state = None
    any_covered = False
    for w in event.writes:
        git_root = oc.repo_root(w.path)
        root = git_root or os.path.realpath(event.cwd)
        rel = oc.rel_to(w.path, root)
        state = state or oc.State(git_root)
        covering = [p for p in packs if p.covers(rel)]
        if not covering:
            continue
        any_covered = True
        file_blocks = []
        for pack in covering:
            try:
                found, n = evaluate(pack, rel, w.text, oc.repo_overrides(root, pack.stack))
            except (OSError, ValueError) as e:
                notes.append(f"{pack.stack}: guard.json unreadable ({e}); no {pack.stack} rule was checked")
                continue
            notes.extend(n)
            for f in found:
                (file_blocks if f["severity"] == "block" else warns).append((rel, w.whole, f))
        if file_blocks:
            blocks.extend(file_blocks)
            ids = sorted({f["id"] for _, _, f in file_blocks})
            if any(not f["overridable"] for _, _, f in file_blocks):
                nonneg = True
            counts = bump_strikes(state, event.session, rel, ids) if state.available else None
            if counts is None:
                notes.append("strike counter unavailable (no git dir or ORCHID_STATE_DIR); "
                             "repeated denials will not escalate to you")
            else:
                max_strike = max([max_strike] + [counts[f["id"]] for _, _, f in file_blocks if f["overridable"]])
        elif state.available:
            clear_strikes(state, event.session, rel)
    if not packs and event.writes and (state or oc.State("")).once(event.session, "no-packs"):
        notes.append("convention-core found no stack pack; nothing is enforced. Install one such as convention-swift.")
    return blocks, warns, notes, max_strike, nonneg, any_covered


def render_claude(blocks, warns, notes, max_strike, nonneg):
    out = {}
    if notes:
        msg = "Orchid convention guard could not check everything:\n" + "\n".join("- " + n for n in notes)
        out["systemMessage"] = msg
    if blocks:
        ordered = sorted(blocks, key=lambda b: (b[2]["overridable"], b[0], b[2]["id"]))
        by_file = {}
        for rel, whole, f in ordered:
            by_file.setdefault(rel, []).append(describe(f, whole))
        parts = []
        for rel, lines in by_file.items():
            parts.append(f"{rel} breaks {len(lines)} convention rule(s):\n" + "\n".join(lines))
        reason = "\n\n".join(parts)
        if warns:
            reason += "\n\nAlso, non-blocking:\n" + "\n".join(describe(f, w) for _, w, f in warns)
        decision = "deny"
        if not nonneg and max_strike > ESCALATE_AFTER:
            decision = "ask"
            reason = (f"This is attempt {max_strike} at the same convention problem, so the guard is asking "
                      "you instead of denying again.\n\n" + reason + "\n\nApprove to let this write through; "
                      "the later scan still reports it. If the rule is wrong for this repo, record that in "
                      ".orchid/conventions/<stack>.md with 'override: global' and a 'reason:'.")
        else:
            reason = ("Convention guard denied this write. Fix every item below and retry.\n\n" + reason)
        out["hookSpecificOutput"] = {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                     "permissionDecisionReason": reason}
    elif warns or notes:
        ctx = []
        if warns:
            ctx.append("Convention guard, non-blocking:\n" + "\n".join(describe(f, w) for _, w, f in warns))
        if notes:
            ctx.append(out["systemMessage"])
        out["hookSpecificOutput"] = {"hookEventName": "PreToolUse", "additionalContext": "\n\n".join(ctx)}
    return out


def main(argv) -> int:
    host = oc.host_arg(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        event = oc.normalize(payload)
        result = decide(event)
    except Exception as e:  # noqa: BLE001 - a crash must be reported, never read as a pass
        return oc.respond(host, "guard", {"systemMessage": f"Orchid convention guard failed "
                                          f"({type(e).__name__}: {e}); this write was NOT checked."})
    return oc.respond(host, "guard", render_claude(*result[:5]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
