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
/plugin marketplace add jernie-apps/orchid-convention
/plugin install convention-core@orchid-convention
/plugin install convention-swift@orchid-convention
```

A stack pack does nothing on its own: core's engine reads it.

## Set up a repository

Inside the repository, run the `convention-setup` skill (ask for "convention setup"). It finds which packs cover the code, surveys what the code actually does, shows what agrees, deviates and contradicts itself, and **asks before writing**. Then it writes `.orchid/conventions/<stack>.md`, a marker block in `AGENTS.md`, and optionally `.codex/hooks.json`. Commit those. Later, `/convention-override <rule-id> <reason>` records a disagreement and `/convention-health` shows how the rules are firing.

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

Built: the guard, lint and gate layers, the read-only scanner, the Codex adapter, the setup skill and the Swift pack (18 rules).

Tested in CI on Linux and macOS: 85 behaviour tests, every rule's good and bad fixtures run through the real hook, and the Swift scan corpus, where the regex sweep must find every planted sweep violation and none of the trap lines. Hook tests use recorded Claude Code and Codex payloads.

Next: Go, Kotlin and Dart packs.

## License

[MIT](LICENSE)
