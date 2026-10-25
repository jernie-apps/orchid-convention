#!/usr/bin/env python3
"""Score convention scans against a pack's answer key. Python 3.9+ stdlib only.

A scan corpus is a directory of source files with planted violations plus
truth.tsv (rule, file, line, layer, required). layer 'sweep' rows are found by
the deterministic regex sweep; 'judged' rows need the scanner's reading.
required 'no' rows are acceptable findings that count neither for recall nor
as false positives.

Usage:
  score_findings.py prepare <corpus> <dest>
      Make <dest> a git repo holding the corpus, without truth.tsv or any other
      answer material. Its session 'corpus' sees the whole corpus as the change
      set, so a scanner run uses: orchid_scan.py --session corpus ...
  score_findings.py sweep <corpus>
      Prepare a temporary repo, run orchid_scan.py sweep on it, and require every
      required sweep row and no unexpected sweep finding. Deterministic; CI runs it.
  score_findings.py score <truth.tsv> <findings.json> [<findings.json> ...]
      Score one or more scanner runs (seal output or a findings file): recall,
      false positives, and how often independent runs agree on each row.

A finding matches a row when rule and file are equal and the lines are within
two of each other (or either side has no line). Exit 0 when a sweep or score
has full recall of required rows and no false positives, 1 otherwise, 2 on a
usage error. A score is an upper bound: the corpus was written to contain
examples of its rules.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANSWER_FILES = {"truth.tsv", "README.md", "GROUND-TRUTH.md"}


def load_truth(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        if set(r) != {"rule", "file", "line", "layer", "required"} or r["layer"] not in ("sweep", "judged") \
                or r["required"] not in ("yes", "no"):
            raise ValueError(f"{path}: malformed row {r}")
        r["line"] = int(r["line"]) if r["line"].strip().isdigit() else None
    return rows


def matches(row, finding) -> bool:
    if finding.get("rule") != row["rule"] or finding.get("file") != row["file"]:
        return False
    a, b = row["line"], finding.get("line")
    return a is None or not isinstance(b, int) or abs(a - b) <= 2


def score_run(rows, findings):
    scored = [f for f in findings if f.get("rule")]
    found = [any(matches(r, f) for f in scored) for r in rows]
    fps = [f for f in scored if not any(matches(r, f) for r in rows)]
    required = [i for i, r in enumerate(rows) if r["required"] == "yes"]
    return found, fps, required


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd)] + list(args), check=True, capture_output=True)


def prepare(corpus: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    git(dest, "init", "-q")
    git(dest, "config", "user.email", "corpus@example.invalid")
    git(dest, "config", "user.name", "corpus")
    (dest / ".gitkeep").write_text("")
    git(dest, "add", ".gitkeep")
    git(dest, "commit", "-qm", "empty base")
    base = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    for src in sorted(corpus.rglob("*")):
        rel = src.relative_to(corpus)
        if src.is_file() and rel.name not in ANSWER_FILES:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest / rel)
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "corpus")
    # The change set of session 'corpus' is everything since the empty base.
    baselines = dest / ".git" / "orchid-convention" / "baselines"
    baselines.mkdir(parents=True, exist_ok=True)
    (baselines / "corpus.json").write_text(json.dumps({"head": base, "dirty": {}, "time": 0}))


def scan(dest: Path, *args, env=None) -> str:
    proc = subprocess.run([sys.executable, str(HERE / "orchid_scan.py"), "--session", "corpus"] + list(args),
                          cwd=dest, capture_output=True, text=True, env=env, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return proc.stdout


def cmd_sweep(corpus: Path) -> int:
    rows = load_truth(corpus / "truth.tsv")
    env = dict(os.environ)
    env.setdefault("ORCHID_PACKS", str(corpus.parent))
    tmp = Path(tempfile.mkdtemp(prefix="orchid-corpus-"))
    try:
        dest = tmp / "repo"
        prepare(corpus, dest)
        findings = json.loads(scan(dest, "sweep", env=env))["findings"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sweep_rows = [r for r in rows if r["layer"] == "sweep"]
    found, fps, required = score_run(sweep_rows, findings)
    ok = True
    for i, r in enumerate(sweep_rows):
        mark = "found" if found[i] else "MISSED"
        if not found[i] and r["required"] == "yes":
            ok = False
        print(f"{mark}: {r['rule']} {r['file']}:{r['line']}")
    for f in fps:
        ok = False
        print(f"FALSE POSITIVE: {f['rule']} {f['file']}:{f.get('line')} ({f['bucket']})")
    judged = [r for r in rows if r["layer"] == "judged"]
    print(f"not scored here: {len(judged)} judged row(s) need a scanner run (see score)")
    hit = sum(1 for i in required if found[i])
    print(f"{'OK' if ok else 'FAILED'}: sweep recall {hit}/{len(required)}, {len(fps)} false positive(s)")
    return 0 if ok else 1


def cmd_score(truth: Path, runs) -> int:
    rows = load_truth(truth)
    all_found, ok = [], True
    for path in runs:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        found, fps, required = score_run(rows, data.get("findings", []))
        all_found.append(found)
        hit = sum(1 for i in required if found[i])
        print(f"{path}: recall {hit}/{len(required)} required, {len(fps)} false positive(s)")
        for f in fps:
            print(f"  FALSE POSITIVE: {f.get('rule')} {f.get('file')}:{f.get('line')}")
        ok = ok and hit == len(required) and not fps
    if len(runs) > 1:
        print("agreement across runs:")
        for i, r in enumerate(rows):
            if r["required"] != "yes":
                continue
            n = sum(1 for found in all_found if found[i])
            print(f"  {n}/{len(runs)} {r['rule']} {r['file']}:{r['line']} ({r['layer']})")
        stable = sum(1 for i, r in enumerate(rows) if r["required"] == "yes" and all(f[i] for f in all_found))
        req = sum(1 for r in rows if r["required"] == "yes")
        print(f"found by every run: {stable}/{req}")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv) -> int:
    try:
        if len(argv) == 3 and argv[0] == "prepare":
            prepare(Path(argv[1]).resolve(), Path(argv[2]).resolve())
            print(f"prepared {argv[2]}: scan it with orchid_scan.py --session corpus; keep truth.tsv away from the scanner")
            return 0
        if len(argv) == 2 and argv[0] == "sweep":
            return cmd_sweep(Path(argv[1]).resolve())
        if len(argv) >= 3 and argv[0] == "score":
            return cmd_score(Path(argv[1]), argv[2:])
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"score_findings: {e}", file=sys.stderr)
        return 1
    print(__doc__.split("\n\n")[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
