# convention-core

The stack-agnostic half of Orchid Convention. It ships no rules. Each stack pack (`convention-<stack>`) is data that this plugin's engine reads, so a new language needs rule files and manifests, not new scripts.

## A pack's contract

```
plugins/convention-<stack>/
├── .claude-plugin/plugin.json
├── pack.json            # stack id, file globs, lint command
├── guard.json           # the fragment-safe regex rules, mirrored from rules/
├── rules/<id>.md        # one rule per file: YAML frontmatter + Markdown body
└── fixtures/<id>.cases  # good and bad cases for every rule
```

### `pack.json`

```json
{
  "stack": "swift",
  "files": ["**/*.swift"],
  "exclude": ["**/.build/**"],
  "lint": {
    "tool": "swiftlint",
    "args": ["lint", "--quiet", "{config_args}", "--path", "{file}"],
    "config": {"file": ".swiftlint.yml", "args": ["--config", "{config}"]},
    "missing": "swiftlint is not on PATH. Install it with `brew install swiftlint`.",
    "timeout": 45
  }
}
```

`files` decides which stack a path belongs to. `lint` is an argument list, never a shell string. `{file}` is the written file, `{config_args}` expands to `config.args` when a config is found (the repo's own config, searched upward from the file to the repo root, wins over the pack's bundled one) and to nothing otherwise. A stack with no linter declares `"lint": null`.

### Rules

Frontmatter is validated against [`schema/rule.schema.json`](schema/rule.schema.json). The fields that drive enforcement:

- `state`: only an `active` rule can block. `advisory` and `deprecated` report without blocking.
- `overridable: false` is reserved for rules no repo may switch off. It forces `ignorable: false` and `scope: full-repo`, and the guard never escalates such a rule to a human prompt.
- `detect.method`: `regex` (portable POSIX ERE, matched per line by `grep -E`), `lint` (the pack linter's rule), or `model` (the scanner's whole-file judgement).
- `detect.fragment_safe: true` means the rule can be decided from an edit's new text alone. Every such regex rule must be mirrored into `guard.json`, and nothing else may be there.

Rule ids are permanent. Retire a rule with `state: removed`; never delete the file or reuse the id.

### Fixtures

`fixtures/<id>.cases` holds cases separated by directive lines:

```
#> case good: reads the key from the environment
#> path: Sources/App/Config.swift
let apiKey = ProcessInfo.processInfo.environment["API_KEY"]
#> case bad: hardcoded key
#> path: Sources/App/Config.swift
#> expect: swift-security-001
let apiKey = "sk_live_123"
```

`path` is repo-relative and must satisfy the rule's glob. `expect` lists every rule the case breaks. `tool: Edit` replays the case as an edit fragment instead of a whole-file write.

## Hooks

Both layers go through one entry point, `scripts/hook.sh <guard|lint>`, registered in [`hooks/hooks.json`](hooks/hooks.json) for `Edit|Write|MultiEdit`. The scripts accept a Claude Code payload (`Write` content, `Edit` new text, `MultiEdit` edits) or a Codex payload (an `apply_patch` body anywhere in `tool_input`, one file or many), and map both onto the same checks. Only Claude Code output is rendered so far; Codex output is the next adapter.

Packs are discovered, not configured: `ORCHID_PACKS` (a path list) if set, otherwise sibling `convention-*` directories of this plugin (a checkout), otherwise the plugin cache layout `<marketplace>/<plugin>/<version>/`, newest version first. A file belongs to every pack whose `files` globs match its repo-relative path and whose `exclude` globs do not.

### Guard (`PreToolUse`)

For each written file, every covering pack's `guard.json` rules whose `file_glob` matches are run over the new text with `grep -E`, per line, minus lines matching `exclude_pattern`. Then:

- all broken rules are reported in one denial, non-overridable ones first, with line numbers (`line` for a whole write, `inserted line` for an edit or patch hunk);
- strikes are counted per session, file and rule; the third attempt at the same rule on the same file returns `ask` instead of `deny`;
- any non-overridable hit denies, whatever the count;
- a write with no blocking hit clears that file's strikes;
- warn-severity hits are returned as context without a decision;
- an overridable rule switched off in `.orchid/conventions/<stack>.md` (with a reason) is skipped; an attempt to switch off a non-overridable rule is refused and named in the denial;
- a pattern grep rejects, a malformed `guard.json` entry, a crash, or a missing `python3` is reported in `systemMessage` as not checked.

### Lint (`PostToolUse`)

For each written file, each covering pack's `lint` command runs on the whole file with a timeout. Output or a non-zero exit goes back to the agent as a `block` reason (the write already happened; this makes the agent address it). A missing linter, or a pack with `"lint": null`, is reported once per session to both the agent and the human as "lint did NOT run", and a note is left for the gate to surface. A timeout is reported as unfinished, not as clean.

### Gate (`SessionStart`, `Stop`, `SubagentStop`)

At session start, `hook.sh baseline` records `HEAD` and the files already dirty. At every stop, `hook.sh gate` computes the change set with `scripts/orchid_scan.py`: every file that differs from the baseline commit (committed, staged, unstaged or untracked), minus files that were dirty at session start and unchanged since, narrowed to paths an installed pack covers. Its content hash is what a scan seals.

| State of the change set | Gate |
| --- | --- |
| empty | passes silently |
| sealed `clean` | passes silently |
| sealed `standing` (a full-repo rule broken in a file this change does not touch) | passes, says so once |
| sealed `violations` | blocks with the list |
| unsealed, scan in progress for this hash | passes silently |
| unsealed | blocks with the exact scan commands |

A block repeats at most twice per change-set hash. On the third stop the turn ends, the human is told once that the change leaves unscanned (or with violations), and the exit is appended to `exits.jsonl` in state. Degraded-capability notes, such as a missing linter, are surfaced once per session at stop. A missing baseline is reported, not silently treated as "no changes".

Subagents are gated only when their type matches the `gated_agents` plugin option (a regular expression; `*` for all). The scanner itself is never gated.

### Scanner

The [`scanner`](agents/scanner.md) agent and the [`convention-detect`](skills/convention-detect/SKILL.md) skill share one procedure: `begin`, `rules` (the model and lint rules to judge, per changed file), `sweep` (every regex rule over the change set, plus full-repo regex rules over every tracked file), read and judge, write a findings file outside the work tree, then `seal --findings <file>`. The scanner never edits code and never chooses the verdict: `seal` validates the findings, merges the sweep, and derives `violations`, `standing` or `clean`. A sweep hit in a changed file makes the verdict `violations` whatever the scanner claimed.

Buckets: `violation`, `standing`, `advisory`, `unknown-pattern`, `inconsistent`. For `inconsistent` the scanner describes both sides and never picks a winner.

### State

Strike counts, once-per-session notices, degraded-capability notes, session baselines, seals and recorded exits live in the repository's git dir (`.git/orchid-convention/`, or the worktree's git dir), so they never appear in `git status` and never get committed. `ORCHID_STATE_DIR` overrides the location. Outside a git repository there is no state: denials never escalate and notices repeat, and the guard says so.

## Fixture suites

```bash
python3 plugins/convention-core/scripts/run_fixtures.py [<pack-dir> ...]
```

Replays every `.cases` fixture through the real `hook.sh guard`, once as a Claude Code payload and once as a Codex `apply_patch` payload, and asserts the verdict: good cases pass silently; bad cases report exactly the guarded rules they expect, deny when one blocks, and list non-overridable rules first. Expected rules that `guard.json` does not hold (lint or scanner rules) must get no guard output and are listed as not asserted. It then drives the lint layer once per pack and checks that a missing linter is reported once with the pack's message.

## Measuring the scanner

A pack may ship `scan-corpus/`: source files with planted violations and traps, plus `truth.tsv` (`rule`, `file`, `line`, `layer` = `sweep` or `judged`, `required` = `yes` or `no`). `scripts/score_findings.py` uses it in three ways:

```bash
score_findings.py sweep plugins/convention-swift/scan-corpus      # CI: the regex half, deterministic
score_findings.py prepare plugins/convention-swift/scan-corpus /tmp/corpus-repo
score_findings.py score plugins/convention-swift/scan-corpus/truth.tsv run1.json run2.json run3.json
```

`sweep` requires every planted regex violation and no hit on the traps. For the judged half, `prepare` builds a repository without the answer key (its session `corpus` sees the whole corpus as the change set). Then run the scanner there several times, independently, with `orchid_scan.py --session corpus`, keeping `truth.tsv` out of its reach. `score` reports each run's recall and false positives, and how many runs found each row. The number is an upper bound: the corpus was written to contain examples of its rules. Rerun it after any rule change.

## Validation

```bash
python3 plugins/convention-core/scripts/validate_rules.py [--root <checkout>] [--quiet]
```

It checks every pack: the manifest; each rule against the schema; id, file name and stack agreement; that `guard.json` mirrors exactly the fragment-safe regex rules; that every pattern is portable ERE (it rejects `\s`, `\w`, `\d`, `\b` and `(?`, which BSD and GNU grep treat differently); that regex examples behave; that every rule has good and bad fixtures; and that every lint rule appears in the bundled linter config. It uses only the Python standard library. Its YAML reader accepts the frontmatter subset the rules use and rejects the rest, and its schema checker fails on any keyword it does not enforce.

## Repo tier

A repo records its disagreements at `.orchid/conventions/<stack>.md`, one heading per rule:

```markdown
## swift-naming-002
override: global
reason: Generated protocol names come from the API schema.
```

Only rules with `overridable: true` can be switched off this way.

## Status

Schema, validator, guard engine, lint dispatcher, fixture runner, scan gate and scanner. The Codex output adapter and the setup skill are not built yet. The hook contract is exercised with simulated payloads only; no live Claude Code or Codex session has run these hooks.
