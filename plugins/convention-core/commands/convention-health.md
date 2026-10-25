---
description: Show this repository's convention health - rules per layer, overrides, guard strikes, gate exits, degraded checks
---

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/orchid_setup.py" health` from the repository root and summarise the JSON for the human:

- Per stack: how many rules run in each layer (guard, lint, scanner, sweep-only), the active overrides with their reasons, and any **refused** overrides (attempts to switch off a non-overridable rule). Name those first.
- Guard strikes per rule. A rule with many strikes is either catching a real habit or wrong for this repository; say which looks likelier and suggest an override or a fix, but do not apply either.
- Gate: seals recorded, and exits where a change left the session unscanned or with violations.
- Degraded checks, such as a missing linter. Say plainly that those checks did not run.

This reports this repository only. Read-only: change nothing.
