---
name: convention-setup
description: Set up Orchid Convention in the current repository, once, or refresh it. Detects which installed stack packs cover the repo, surveys what the code actually does against the rules, shows the human what agrees, deviates and contradicts, and only after their approval writes the repo tier, the instructions marker block and optionally the Codex hooks. Use for "/convention-setup", "set up conventions", or when the gate or guard reports that no pack covers this repo.
---

# Convention setup

`SETUP` means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/orchid_setup.py"` and `SCAN` means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/orchid_scan.py"`, both run from the repository root. Re-running this skill is safe: every write is idempotent.

**Ask before writing anything.** Steps 1 to 3 only read.

1. **Detect.** Run `SETUP detect`. It lists each installed pack with the number of tracked files it covers, and which repo-tier files, instructions files and Codex hooks already exist. If no pack covers any file, say so and stop: the plugin cannot help this repository until a matching pack is installed.
2. **Survey.** Run `SCAN sweep --all` for the deterministic picture of every regex rule across the repository. Then read a representative sample of covered files (at least ten per stack, spread across directories) against the rules that need judgement; the rule files are listed under each pack's `rules/` directory. Do not edit anything.
3. **Report in three groups**, with counts and file references:
   - **Agrees**: rules the repository already follows.
   - **Deviates**: rules it breaks in a minority of places (candidate fixes, or candidate overrides if the deviation is deliberate).
   - **Contradicts itself**: places where the repository has two competing shapes for the same thing. Describe both sides. **Do not pick a winner**; that is the human's decision.

   Name any non-overridable rule that is broken (secrets, personal data in logs) separately and first. Those cannot be overridden; they need fixing (and a leaked secret needs rotating).
4. **Ask** the human which stacks to enable, which deviations to record as overrides (each needs a reason in their words), and whether to install Codex hooks.
5. **Write**, only what was approved:
   - `SETUP init --stacks <stack,...>`, adding `--codex` if they asked for Codex hooks.
   - `SETUP override <rule-id> <reason>` for each approved override. A refusal (exit 3) means the rule is non-overridable; tell the human, do not work around it.
6. **Report** the files written and remind the human to review and commit `.orchid/conventions/`, the marker block and `.codex/hooks.json`. Hook state lives in the git directory and is never committed.
