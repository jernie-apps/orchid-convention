# Orchid Convention development

- `plugins/convention-core`: stack-agnostic machinery (rule schema, generic guard, lint dispatch, scan gate, scanner agent, skills). Ships no rules.
- `plugins/convention-<stack>`: one pack per language: rule files (Markdown + YAML frontmatter validated by the core schema), `guard.json` (fragment-safe subset), lint script, good/bad fixtures.
- Hooks must work in Claude Code (plugin `hooks/hooks.json`) and Codex (`.codex/hooks.json`). Map both onto the same core scripts.
- Tooling: bash (macOS bash 3.2 compatible), jq, python3 stdlib, git. No other runtime deps.
- The scanner never edits the code it judges. Security rules (secrets, PII in logs) are never overridable.
- A missing linter or a hook that did not run is never a pass: say so.
- Every rule ships with good and bad fixtures; CI runs the fixture suites.
- ≤10 changed code files per PR, counting tests, fixtures and scripts.
