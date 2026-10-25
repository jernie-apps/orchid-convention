# Codex adapter

`hooks.json` here is a template for a repository's `.codex/hooks.json`. It runs the same `scripts/hook.sh` layers as Claude Code with `--host codex`. Replace `__ORCHID_CORE__` with the absolute path of an installed `convention-core`; `/convention-setup` does this.

## What is verified

- Input: the layers accept a Codex payload whose `tool_input` carries an `apply_patch` body anywhere (a `command` array, an `input` string, or similar), including multi-file patches with add, update, move and delete. `tests/test_codex.py` and `run_fixtures.py` exercise it with simulated payloads.
- Output: `--host codex` is translated by `orchid_common.respond()`, and the tests pin that translation.

## What is assumed

The current Codex hooks documentation could not be reached when this adapter was written, so these points come from the Claude Code hook contract that Codex hooks are modelled on. **None has been checked against a live Codex.**

1. The config shape (`hooks` → event → `[{matcher, hooks: [{type: command, command, timeout}]}]`), the event names `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`, and the tool name `apply_patch` in matchers.
2. The payload carries `session_id`, `cwd` and `tool_input` (and `hook_event_name`). If the session id has another name, the layers fall back to `conversation_id`, `thread_id`, then a fixed id; strikes and once-per-session notices then pool across sessions.
3. Exit status 2 with the reason on stderr blocks: it denies a tool call (PreToolUse), returns findings to the agent (PostToolUse), or keeps the turn going (Stop).
4. A `systemMessage` JSON object on stdout with exit status 0 is shown, not acted on.
5. There is no "ask the human" outcome. Where Claude Code would get `ask` after two denials, Codex gets a denial telling the agent to stop retrying and hand the decision to the user. Non-overridable rules deny either way.

If any assumption is wrong, the fix belongs in `respond()` (one function) and this template, not in the layers.
