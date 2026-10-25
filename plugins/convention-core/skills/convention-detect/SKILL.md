---
name: convention-detect
description: How to scan the current change set against the installed convention packs and seal it so the convention gate lets the turn end. Use when the Orchid convention gate blocks a stop with "has not sealed this change set", or when asked to run a convention scan. Report-only; never edit the code being judged.
---

# Convention scan

You judge code against the installed convention rules and write down what you find. **You never edit, fix, format or stage the code you are judging.** A scanner that fixes things reports clean and the finding is lost. If you are the agent that wrote the code, fixing comes after the seal, in a separate step, followed by a new scan.

`SCAN` below means the command the gate printed, `python3 "<core>/scripts/orchid_scan.py" --session <id>`, run from inside the repository.

## Steps

1. `SCAN begin`: marks the scan as in progress, so the gate stays quiet while you work. It prints the change-set hash.
2. `SCAN rules`: lists, for each changed file, the rules you must judge by reading (`method: model` and `lint`) and the path of each rule file. Read every rule file you are given, the frontmatter and the body.
3. `SCAN sweep`: the deterministic part. Every regex rule over the changed files, and full-repo regex rules over the whole repository. Do not repeat these; `seal` re-runs the sweep and merges it.
4. Read each changed file in full and judge each rule listed for it. Use the rule's `statement`, `examples` and body. When unsure, say so in `evidence` rather than guessing a verdict.
5. Write the findings file (format below) **outside the repository work tree**, for example in a temporary directory.
6. `SCAN seal --findings <file>`: validates your findings, merges the sweep, derives the verdict and seals the hash. You do not choose the verdict.
7. Report the printed verdict and counts. Stop.

If a file changes after step 1, the hash changes and the seal will not match. That is correct: the gate will ask for a new scan.

## Buckets

| Bucket | Meaning | Blocks |
| --- | --- | --- |
| `violation` | An active, blocking rule broken in a file in this change set | yes |
| `standing` | A `scope: full-repo` rule broken in a file this change set does not touch | no, reported |
| `advisory` | An advisory, deprecated, `warn` or `info` rule broken anywhere | no |
| `unknown-pattern` | A recurring pattern no rule covers; raw material for a new rule | no |
| `inconsistent` | The repository contradicts itself (two shapes for the same thing) | no |

For `inconsistent`, describe both sides with counts and file references. **Never pick a winner**; that is a human decision.

A rule switched off in `.orchid/conventions/<stack>.md` with `override: global` and a reason is not judged. A block that tries to switch off an `overridable: false` rule is itself a finding: report it as `inconsistent` with the override file as `file`.

## Findings file

```json
{
  "findings": [
    {"bucket": "violation", "rule": "swift-security-003", "file": "Sources/App/Ship.swift",
     "line": 12, "evidence": "recipient name and street concatenated into print()"},
    {"bucket": "inconsistent", "file": "Sources/App/Features",
     "evidence": "41 handlers use didTapX, 6 use xTapped; no rule decides"}
  ]
}
```

- `bucket`, `file` (repo-relative) and `evidence` are required. `rule` is required for `violation`, `standing` and `advisory`. `line` is optional.
- `violation` must name a file in the change set; anything else broken is `standing` or `advisory`.
- An empty list is a valid result: `{"findings": []}`.
