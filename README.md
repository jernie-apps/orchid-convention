# Orchid Convention

Enforces a project's coding conventions while an agent writes code, in Claude Code and Codex. A stack-agnostic core plus one rule pack per language: Swift first, with Go, Kotlin and Dart planned.

| Plugin | What it holds |
| --- | --- |
| [`convention-core`](plugins/convention-core/README.md) | The rule schema, the validator, one guard engine, one lint dispatcher, the scan gate and the read-only scanner. Ships no rules. |
| [`convention-swift`](plugins/convention-swift/README.md) | Swift 6 and SwiftUI rules, their guard patterns, fixtures and a SwiftLint config. Data only. |

## How it works

A change meets three layers in order.

1. **Guard** (before a write): rules that can be decided from the new text alone are checked before the file changes. Every broken rule is reported in one denial. After two denials for the same rule on the same file, the third attempt asks the human instead. Non-overridable rules (secrets, personal data in logs) keep denying and never escalate.
2. **Lint** (after a write): the pack's own linter runs over the whole file. If the linter is not installed, the session is told once that lint did not run. That is never reported as a pass.
3. **Gate** (before the turn ends): rules that need the whole file or the whole repo are checked by a read-only scan, and the turn cannot end until the current change set has been scanned and sealed. A change set that stays unscanned is blocked twice, then let through with a recorded warning.

A repo can switch off an overridable rule in writing at `.orchid/conventions/<stack>.md`. Security rules cannot be switched off there.

## Install (Claude Code)

```
/plugin marketplace add companie-apps/orchid-convention
/plugin install convention-core@orchid-convention
/plugin install convention-swift@orchid-convention
```

A stack pack does nothing on its own: core's engine reads it.

## Use with Codex

Copy [`plugins/convention-core/codex/hooks.json`](plugins/convention-core/codex/hooks.json) to the repository's `.codex/hooks.json` and replace `__ORCHID_CORE__` with the path of a `convention-core` checkout or install. The layers are the same; the Codex output conventions are assumptions, listed in [`codex/README.md`](plugins/convention-core/codex/README.md).

## Requirements

`bash` (macOS bash 3.2 works), `jq`, `python3` (3.9 or newer, standard library only) and `git`. A pack's linter, such as `swiftlint`, is optional; without it the lint layer reports that it did not run.

## Working on this repo

```bash
python3 plugins/convention-core/scripts/validate_rules.py   # schema and pack invariants
python3 -m unittest discover -s tests -v                     # behaviour tests
python3 plugins/convention-core/scripts/run_fixtures.py      # every pack's fixtures through the real hook
```

CI runs all three on Linux with the oldest supported Python and on macOS with the system bash and Python. Repository rules are in [`AGENTS.md`](AGENTS.md).

## Status

Guard, lint and gate layers, the Codex adapter and the Swift pack are built and tested with simulated Claude Code and Codex payloads; the setup skill follows in a separate pull request. Nothing here has been exercised against a live Claude Code or Codex session yet.
