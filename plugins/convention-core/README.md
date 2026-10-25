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

Schema and validator only. The guard engine and lint dispatcher arrive in the next pull request, and the scan gate after that.
