---
description: Record a repo-tier override that switches off an overridable convention rule, with a reason
argument-hint: <rule-id> <reason>
---

Record a repository override for a convention rule. Arguments: `$ARGUMENTS` (a rule id, then the reason).

1. If there is no reason after the rule id, ask the human for one in their own words. Do not invent it.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/orchid_setup.py" override $ARGUMENTS` from the repository root.
3. If it exits 3, the rule is non-overridable (security). Report that and stop; do not edit `.orchid/conventions/` by hand to get around it, because the guard and scanner ignore such blocks anyway and the scanner reports them.
4. Otherwise show the written block and the file. Say that it applies from the next guard check and scan, not retroactively, and that the file should be committed so the next person can read the decision.
