#!/usr/bin/env python3
"""Change set, deterministic sweep and seal for the scan gate. Python 3.9+ stdlib only.

The gate (orchid_gate.py) and the scanner agent both call this one module, so
they cannot disagree about which files are in the scan or what its hash is.

Usage (run from anywhere inside the repository):
  orchid_scan.py [--session ID] list      changed files the installed packs cover
  orchid_scan.py [--session ID] hash      16-hex content hash of that change set
  orchid_scan.py [--session ID] rules     per changed file, the rules the scanner must judge
  orchid_scan.py [--session ID] sweep [--all]
                                          every regex rule over the change set, plus
                                          full-repo rules over every tracked file
  orchid_scan.py [--session ID] begin     mark a scan of the current hash as in progress
  orchid_scan.py [--session ID] seal --findings FILE
                                          merge the scanner's findings with the sweep,
                                          derive the verdict, and seal the current hash
  orchid_scan.py [--session ID] status    JSON: hash, files, seal, baseline

The change set is every file that differs from the session baseline's commit
(committed, staged, unstaged or untracked), minus files that were already dirty
at session start and have not changed since, narrowed to paths some installed
pack covers. Without a baseline, HEAD is the base and the result says so.

The scanner never chooses the verdict. seal derives it: any violation (from
the scanner or the sweep) gives 'violations'; otherwise any standing finding
gives 'standing'; otherwise 'clean'. Exit 0 on success, 1 on a usage or
validation error, 2 when the repository cannot be read.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchid_common as oc  # noqa: E402
import validate_rules as vr  # noqa: E402

BUCKETS = ("violation", "standing", "advisory", "unknown-pattern", "inconsistent")
IN_PROGRESS_SECONDS = 20 * 60


class ScanError(Exception):
    pass


def git(root: str, *args, check=True) -> str:
    proc = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=30)
    if check and proc.returncode != 0:
        raise ScanError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def head(root: str) -> str:
    out = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "HEAD"],
                         capture_output=True, text=True, timeout=10)
    return out.stdout.strip() if out.returncode == 0 else ""


def blob(root: str, rel: str) -> str:
    return git(root, "hash-object", "--", rel).strip()


def dirty_paths(root: str, base: str):
    names = set()
    if base:
        names.update(x for x in git(root, "diff", "--name-only", "-z", base).split("\0") if x)
    else:
        names.update(x for x in git(root, "ls-files", "-z").split("\0") if x)
    names.update(x for x in git(root, "ls-files", "-z", "--others", "--exclude-standard").split("\0") if x)
    return sorted(names)


class Repo:
    def __init__(self, cwd: str, session: str = ""):
        self.root = oc.repo_root(os.path.realpath(cwd))
        if not self.root:
            raise ScanError("not inside a git repository")
        self.state = oc.State(self.root)
        self.packs, self.problems = oc.discover_packs()
        self.session = session or self._latest_session()
        self.baseline = self._read_baseline()

    def _latest_session(self) -> str:
        if not self.state.available:
            return ""
        files = sorted((self.state.dir / "baselines").glob("*.json"), key=lambda p: p.stat().st_mtime)
        return files[-1].stem if files else ""

    def _read_baseline(self):
        if not self.state.available or not self.session:
            return None
        try:
            return json.loads((self.state.dir / "baselines" / f"{_safe(self.session)}.json").read_text())
        except (OSError, ValueError):
            return None

    def record_baseline(self) -> dict:
        base = head(self.root)
        dirty = {}
        for rel in dirty_paths(self.root, base):
            if os.path.isfile(os.path.join(self.root, rel)):
                dirty[rel] = blob(self.root, rel)
        data = {"head": base, "dirty": dirty, "time": int(time.time())}
        if self.state.available:
            d = self.state.dir / "baselines"
            d.mkdir(exist_ok=True)
            (d / f"{_safe(self.session)}.json").write_text(json.dumps(data))
            old = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-32]
            for p in old:
                p.unlink()
        return data

    def covered(self, rel: str) -> list:
        return [p for p in self.packs if p.covers(rel)]

    def changed(self):
        """Return (entries, warnings); entries are (rel, blob) sorted by path."""
        warnings = []
        if self.baseline is None:
            warnings.append("no session baseline (the SessionStart hook did not run for this session); "
                            "the change set is measured against HEAD, so changes already committed this "
                            "session are not included")
            base, dirty = head(self.root), {}
        else:
            base, dirty = self.baseline.get("head", ""), self.baseline.get("dirty", {})
        entries = []
        for rel in dirty_paths(self.root, base):
            full = os.path.join(self.root, rel)
            if not os.path.isfile(full) or not self.covered(rel):
                continue
            b = blob(self.root, rel)
            if dirty.get(rel) == b:
                continue
            entries.append((rel, b))
        return entries, warnings

    @staticmethod
    def digest(entries) -> str:
        h = hashlib.sha256()
        for rel, b in entries:
            h.update(f"{rel}\0{b}\n".encode())
        return h.hexdigest()[:16]

    def rules(self, pack):
        out = []
        for path in sorted((pack.dir / "rules").glob("*.md")):
            try:
                fm, _ = vr.read_frontmatter(path)
            except (vr.YamlError, OSError, UnicodeDecodeError) as e:
                raise ScanError(f"{path}: {e}")
            if fm.get("state") in ("proposed", "removed"):
                continue
            fm["_path"] = str(path)
            out.append(fm)
        return out

    def applicable(self, rel: str):
        out = []
        for pack in self.covered(rel):
            overrides = oc.repo_overrides(self.root, pack.stack)
            for rule in self.rules(pack):
                det = rule["detect"]
                if not oc.glob_match(det["file_glob"], rel):
                    continue
                if det.get("exclude_glob") and oc.glob_match(det["exclude_glob"], rel):
                    continue
                if rule["overridable"] and rule["id"] in overrides:
                    continue
                out.append(rule)
        return out

    def sweep(self, entries, everything: bool = False):
        changed = {rel for rel, _ in entries}
        tracked = [x for x in git(self.root, "ls-files", "-z").split("\0") if x]
        pool = sorted(set(tracked) | changed)
        findings = []
        for rel in pool:
            if not self.covered(rel) or not os.path.isfile(os.path.join(self.root, rel)):
                continue
            in_change = rel in changed
            for rule in self.applicable(rel):
                det = rule["detect"]
                if det["method"] != "regex":
                    continue
                if not in_change and not everything and rule["scope"] != "full-repo":
                    continue
                text = Path(self.root, rel).read_text(encoding="utf-8", errors="replace")
                try:
                    hits = vr.regex_hits(det, text)
                except RuntimeError as e:
                    raise ScanError(f"{rule['id']}: pattern could not be evaluated: {e}")
                for line in sorted(hits):
                    if rule["state"] != "active" or rule["severity"] != "block":
                        bucket = "advisory"
                    elif in_change:
                        bucket = "violation"
                    else:
                        bucket = "standing"
                    findings.append({"rule": rule["id"], "file": rel, "line": line, "bucket": bucket,
                                     "source": "sweep"})
        return findings

    def seal_path(self, digest: str) -> Path:
        return self.state.dir / "seals" / f"{digest}.json"

    def read_seal(self, digest: str):
        if not self.state.available:
            return None
        try:
            return json.loads(self.seal_path(digest).read_text())
        except (OSError, ValueError):
            return None


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:120] or "no-session"


def validate_findings(data, entries) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ScanError('findings file must be {"findings": [...]}')
    changed = {rel for rel, _ in entries}
    out = []
    for i, f in enumerate(data["findings"]):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            raise ScanError(f"{where}: must be an object")
        if f.get("bucket") not in BUCKETS:
            raise ScanError(f"{where}: bucket must be one of {list(BUCKETS)}")
        if f["bucket"] in ("violation", "standing", "advisory"):
            if not isinstance(f.get("rule"), str) or not vr.ID_RE.match(f["rule"]):
                raise ScanError(f"{where}: a {f['bucket']} finding needs a rule id")
        if not isinstance(f.get("file"), str) or not f["file"]:
            raise ScanError(f"{where}: needs a repo-relative file")
        if f["bucket"] == "violation" and f["file"] not in changed:
            raise ScanError(f"{where}: {f['file']} is not in this change set; report it as standing")
        if not isinstance(f.get("evidence", ""), str):
            raise ScanError(f"{where}: evidence must be a string")
        out.append(dict(f, source="scanner"))
    return out


def verdict_of(findings) -> str:
    buckets = {f["bucket"] for f in findings}
    if "violation" in buckets:
        return "violations"
    if "standing" in buckets:
        return "standing"
    return "clean"


def main(argv) -> int:
    args = list(argv)
    session = ""
    if args[:1] == ["--session"] and len(args) > 1:
        session = args[1]
        args = args[2:]
    if not args:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 1
    cmd = args.pop(0)
    try:
        repo = Repo(os.getcwd(), session)
        if cmd == "baseline":
            data = repo.record_baseline()
            print(json.dumps({"session": repo.session, "head": data["head"], "dirty": len(data["dirty"])}))
            return 0
        entries, warnings = repo.changed()
        for w in warnings + repo.problems:
            print(f"warning: {w}", file=sys.stderr)
        digest = repo.digest(entries)
        if cmd == "list":
            for rel, _ in entries:
                print(rel)
        elif cmd == "hash":
            print(digest)
        elif cmd == "rules":
            plan = {rel: [{"id": r["id"], "method": r["detect"]["method"], "severity": r["severity"],
                           "state": r["state"], "overridable": r["overridable"], "file": r["_path"]}
                          for r in repo.applicable(rel) if not (r["detect"]["method"] == "regex")]
                    for rel, _ in entries}
            print(json.dumps({"hash": digest, "files": plan}, indent=2))
        elif cmd == "sweep":
            print(json.dumps({"hash": digest, "findings": repo.sweep(entries, "--all" in args)}, indent=2))
        elif cmd == "begin":
            repo.state.update("scanning.json", lambda d: d.update(hash=digest, time=int(time.time())))
            print(digest)
        elif cmd == "seal":
            if args[:1] != ["--findings"] or len(args) < 2:
                raise ScanError("seal needs --findings FILE")
            if not repo.state.available:
                raise ScanError("no state directory; cannot seal")
            scanner = validate_findings(json.loads(Path(args[1]).read_text(encoding="utf-8")), entries)
            findings = scanner + repo.sweep(entries)
            verdict = verdict_of(findings)
            seal = {"hash": digest, "verdict": verdict, "time": int(time.time()), "session": repo.session,
                    "files": [rel for rel, _ in entries], "findings": findings}
            repo.seal_path(digest).parent.mkdir(exist_ok=True)
            repo.seal_path(digest).write_text(json.dumps(seal, indent=2))
            repo.state.update("scanning.json", lambda d: d.clear())
            print(json.dumps({"hash": digest, "verdict": verdict,
                              "counts": {b: sum(1 for f in findings if f["bucket"] == b) for b in BUCKETS}}))
        elif cmd == "status":
            print(json.dumps({"hash": digest, "files": [r for r, _ in entries], "seal": repo.read_seal(digest),
                              "baseline": repo.baseline is not None, "session": repo.session}, indent=2))
        else:
            raise ScanError(f"unknown command '{cmd}'")
    except ScanError as e:
        print(f"orchid_scan: {e}", file=sys.stderr)
        return 2 if "git" in str(e) else 1
    except (OSError, ValueError) as e:
        print(f"orchid_scan: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
