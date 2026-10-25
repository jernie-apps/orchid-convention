#!/usr/bin/env python3
"""Repository setup, overrides and health for Orchid Convention. Python 3.9+ stdlib only.

Run from inside the target repository.

  orchid_setup.py detect
      JSON: which installed packs cover tracked files, with counts and examples,
      and which repo-tier files already exist. Writes nothing.
  orchid_setup.py init --stacks swift[,go...] [--codex]
      Idempotent. Creates .orchid/conventions/<stack>.md when missing, writes
      or refreshes the marker block in AGENTS.md (or CLAUDE.md when that is the
      only instructions file), and with --codex installs .codex/hooks.json from
      the template, merging into an existing file without dropping its hooks.
  orchid_setup.py override <rule-id> <reason...>
      Records 'override: global' with the reason and today's date for an
      overridable rule. Refuses a non-overridable rule (exit 3) or an empty
      reason (exit 1). Re-running replaces the rule's block.
  orchid_setup.py health
      JSON: per stack, rules by layer, active and refused overrides, guard
      strikes per rule, gate exits, seals and degraded notes in this repo.

Exit 0 on success, 1 on a usage error, 2 outside a git repository, 3 on a refusal.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchid_common as oc  # noqa: E402
import validate_rules as vr  # noqa: E402

CORE = Path(__file__).resolve().parents[1]
BEGIN = "<!-- orchid-convention:begin -->"
END = "<!-- orchid-convention:end -->"
PLACEHOLDER = "__ORCHID_CORE__"


class Refusal(Exception):
    pass


def git_root() -> str:
    root = oc.repo_root(os.path.realpath(os.getcwd()))
    if not root:
        raise SystemExit(_fail("not inside a git repository", 2))
    return root


def _fail(msg: str, code: int) -> int:
    print(f"orchid_setup: {msg}", file=sys.stderr)
    return code


def tracked(root: str):
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [x for x in out.split("\0") if x]


def pack_rules(pack):
    rules = []
    for path in sorted((pack.dir / "rules").glob("*.md")):
        fm, _ = vr.read_frontmatter(path)
        rules.append(fm)
    return rules


def find_rule(packs, rid):
    for pack in packs:
        for rule in pack_rules(pack):
            if rule.get("id") == rid:
                return pack, rule
    return None, None


def detect(root: str) -> dict:
    packs, problems = oc.discover_packs()
    files = tracked(root)
    stacks = {}
    for pack in packs:
        hits = [f for f in files if pack.covers(f)]
        stacks[pack.stack] = {"files": len(hits), "examples": hits[:5],
                              "repo_tier": os.path.isfile(os.path.join(root, ".orchid", "conventions",
                                                                       f"{pack.stack}.md"))}
    return {"root": root, "stacks": stacks, "problems": problems,
            "instructions": [n for n in ("AGENTS.md", "CLAUDE.md") if os.path.exists(os.path.join(root, n))],
            "codex_hooks": os.path.isfile(os.path.join(root, ".codex", "hooks.json"))}


def repo_tier_template(stack: str) -> str:
    return (f"# {stack} conventions: repo tier\n\n"
            f"Repository-specific decisions about the {stack} rules shipped by convention-{stack}.\n"
            "Switch off an overridable rule with a heading naming its id, then `override: global` and a\n"
            "`reason:` line. Non-overridable rules (security) cannot be switched off here. Prefer\n"
            "`orchid_setup.py override <rule-id> <reason>`, which checks that for you.\n")


def marker_block(stacks) -> str:
    return (f"{BEGIN}\n## Coding conventions (Orchid Convention)\n\n"
            f"This repository enforces the {', '.join(sorted(stacks))} convention pack(s) while code is written:\n\n"
            "- Writes that break a fragment-safe rule are denied before they land; fix every listed rule.\n"
            "- The pack linter runs after each write. If it is missing you are told once; lint then counts as not tested.\n"
            "- The turn cannot end until the change set is scanned and sealed. Use the convention-core scanner "
            "agent or the convention-detect skill; the scanner never edits code.\n"
            "- Repo decisions live in `.orchid/conventions/<stack>.md`. Security rules cannot be overridden there.\n"
            f"{END}\n")


def write_marker(root: str, stacks) -> str:
    target = None
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            target = os.path.realpath(p)
            break
    if target is None:
        target = os.path.join(root, "AGENTS.md")
    text = Path(target).read_text(encoding="utf-8") if os.path.exists(target) else ""
    block = marker_block(stacks)
    if BEGIN in text and END in text:
        start, end = text.index(BEGIN), text.index(END) + len(END)
        tail = text[end:]
        new = text[:start] + block.rstrip("\n") + tail
    else:
        new = text + ("\n" if text and not text.endswith("\n") else "") + ("\n" if text else "") + block
    if new != text:
        Path(target).write_text(new, encoding="utf-8")
    return os.path.relpath(target, root)


def install_codex(root: str) -> str:
    template = json.loads((CORE / "codex" / "hooks.json").read_text(encoding="utf-8"))
    ours = json.loads(json.dumps(template).replace(PLACEHOLDER, str(CORE).replace("\\", "/")))
    path = Path(root) / ".codex" / "hooks.json"
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise Refusal(f"{path} is not valid JSON; fix or remove it first")
    else:
        current = {}
    hooks = current.setdefault("hooks", {})
    for event, groups in ours["hooks"].items():
        existing = hooks.setdefault(event, [])
        # Drop earlier orchid entries (any core path), then add the current one.
        existing[:] = [g for g in existing
                       if not any("scripts/hook.sh" in h.get("command", "") and "--host codex" in h.get("command", "")
                                  for h in g.get("hooks", []))]
        existing.extend(groups)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return os.path.relpath(path, root)


def init(root: str, stacks, codex: bool) -> dict:
    packs, _ = oc.discover_packs()
    known = {p.stack for p in packs}
    unknown = [s for s in stacks if s not in known]
    if unknown:
        raise Refusal(f"no installed pack for: {', '.join(unknown)} (installed: {', '.join(sorted(known)) or 'none'})")
    written = []
    conv = Path(root) / ".orchid" / "conventions"
    for stack in stacks:
        p = conv / f"{stack}.md"
        if not p.exists():
            conv.mkdir(parents=True, exist_ok=True)
            p.write_text(repo_tier_template(stack), encoding="utf-8")
            written.append(os.path.relpath(p, root))
    written.append(write_marker(root, stacks))
    if codex:
        written.append(install_codex(root))
    return {"written": written}


def override(root: str, rid: str, reason: str) -> dict:
    if not vr.ID_RE.match(rid):
        raise ValueError(f"'{rid}' is not a rule id")
    reason = " ".join(reason.split())
    if not reason:
        raise ValueError("an override needs a reason")
    packs, _ = oc.discover_packs()
    pack, rule = find_rule(packs, rid)
    if rule is None:
        raise ValueError(f"no installed rule {rid}")
    if rule.get("overridable") is not True:
        raise Refusal(f"{rid} is non-overridable ({rule.get('title')}); no repo can switch it off. "
                      "Fix the code, or propose a rule change upstream.")
    path = Path(root) / ".orchid" / "conventions" / f"{pack.stack}.md"
    text = path.read_text(encoding="utf-8") if path.exists() else repo_tier_template(pack.stack)
    block = f"## {rid}\noverride: global\nreason: {reason}\nrecorded: {datetime.date.today().isoformat()}\n"
    lines = text.split("\n")
    out, skipping = [], False
    for line in lines:
        m = re.match(r"^#+\s+`?([^\s`]+)`?\s*$", line)
        if m:
            skipping = m.group(1) == rid
        if not skipping:
            out.append(line)
    text = "\n".join(out).rstrip("\n") + "\n\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"file": os.path.relpath(path, root), "rule": rid, "title": rule.get("title"),
            "applies": "from the next guard check and scan; not retroactive"}


def health(root: str) -> dict:
    packs, problems = oc.discover_packs()
    state = oc.State(root)
    strikes, exits, seals, degraded = {}, [], 0, []
    if state.available:
        try:
            data = json.loads((state.dir / "guard-strikes.json").read_text())
            for sess in data.values():
                for counts in (sess.get("files", {}) if isinstance(sess, dict) else {}).values():
                    for rid, n in counts.items():
                        strikes[rid] = strikes.get(rid, 0) + n
        except (OSError, ValueError):
            pass
        try:
            exits = [json.loads(x) for x in (state.dir / "exits.jsonl").read_text().splitlines() if x.strip()]
        except (OSError, ValueError):
            exits = []
        seals = len(list((state.dir / "seals").glob("*.json"))) if (state.dir / "seals").is_dir() else 0
        d = state.dir / "degraded"
        degraded = sorted(p.read_text().strip() for p in d.glob("*")) if d.is_dir() else []
    report = {"root": root, "state": str(state.dir) if state.available else None, "problems": problems,
              "stacks": {}, "gate": {"seals": seals, "exits": len(exits),
                                     "unscanned_exits": sum(1 for e in exits if e.get("why") == "unscanned")},
              "degraded": degraded}
    for pack in packs:
        rules = pack_rules(pack)
        guard_ids = {r.get("id") for r in pack.guard_rules()}
        overrides = oc.repo_overrides(root, pack.stack)
        by_id = {r["id"]: r for r in rules}
        layers = {"guard": 0, "lint": 0, "scanner": 0, "sweep-only": 0}
        for r in rules:
            m = r["detect"]["method"]
            layers["guard" if r["id"] in guard_ids else "lint" if m == "lint" else "scanner" if m == "model"
                   else "sweep-only"] += 1
        report["stacks"][pack.stack] = {
            "rules": len(rules), "layers": layers,
            "overrides": {rid: why for rid, why in overrides.items() if by_id.get(rid, {}).get("overridable")},
            "refused_overrides": sorted(rid for rid in overrides if by_id.get(rid, {}).get("overridable") is False),
            "unknown_overrides": sorted(rid for rid in overrides if rid not in by_id),
            "guard_strikes": {rid: n for rid, n in sorted(strikes.items()) if rid in by_id},
        }
    return report


def main(argv) -> int:
    if not argv:
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        return 1
    cmd, args = argv[0], argv[1:]
    root = git_root()
    try:
        if cmd == "detect":
            result = detect(root)
        elif cmd == "init":
            stacks, codex = [], "--codex" in args
            if "--stacks" in args and args.index("--stacks") + 1 < len(args):
                stacks = [s for s in args[args.index("--stacks") + 1].split(",") if s]
            if not stacks:
                return _fail("init needs --stacks <stack>[,<stack>...]", 1)
            result = init(root, stacks, codex)
        elif cmd == "override":
            if len(args) < 2:
                return _fail("override needs <rule-id> <reason...>", 1)
            result = override(root, args[0], " ".join(args[1:]))
        elif cmd == "health":
            result = health(root)
        else:
            return _fail(f"unknown command '{cmd}'", 1)
    except Refusal as e:
        return _fail(f"refused: {e}", 3)
    except (ValueError, OSError, vr.YamlError) as e:
        return _fail(str(e), 1)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
