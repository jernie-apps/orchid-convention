"""Shared plumbing for the convention-core hooks. Python 3.9+ standard library only.

Hosts send different hook payloads. normalize() turns a Claude Code
(Write/Edit/MultiEdit) or Codex (apply_patch) payload into the same Event, so
the guard and lint layers never look at host-specific fields.

Packs are found, never configured: ORCHID_PACKS first, then sibling
convention-* directories of this plugin (a checkout), then the plugin cache
layout <marketplace>/<plugin>/<version>/. A pack is any directory holding a
pack.json; its stack id decides which files it governs.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z][a-z0-9]*-[a-z]+-[0-9]{3}$")
PATCH_RE = re.compile(r"\*\*\* Begin Patch\n.*?(?:\n\*\*\* End Patch|\Z)", re.S)


class Write:
    """One file the tool call creates or changes.

    text is what the guard judges: the whole new content for a write, or only
    the inserted lines for an edit or patch hunk. whole is True when text is
    the entire file.
    """

    def __init__(self, path: str, text: str, whole: bool):
        self.path = path
        self.text = text
        self.whole = whole


class Event:
    def __init__(self, host, name, session, cwd, tool, writes):
        self.host = host
        self.name = name
        self.session = session
        self.cwd = cwd
        self.tool = tool
        self.writes = writes


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def parse_apply_patch(patch: str):
    """Yield (path, added_text, whole) for each file an apply_patch body touches."""
    path, added, whole = None, [], False

    def flush():
        if path is not None:
            return Write(path, "\n".join(added) + ("\n" if added else ""), whole)
        return None

    out = []
    for line in patch.split("\n"):
        m = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if m:
            w = flush()
            if w:
                out.append(w)
            kind, target = m.group(1), m.group(2).strip()
            path, added, whole = (None if kind == "Delete" else target), [], kind == "Add"
            continue
        m = re.match(r"^\*\*\* Move to: (.+)$", line)
        if m and path is not None:
            path = m.group(1).strip()
            continue
        if path is not None and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    w = flush()
    if w:
        out.append(w)
    return out


def normalize(payload: dict) -> Event:
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {"input": ti}
    cwd = str(payload.get("cwd") or os.getcwd())
    session = str(payload.get("session_id") or payload.get("conversation_id")
                  or payload.get("thread_id") or "no-session")
    name = str(payload.get("hook_event_name") or "")
    writes = []
    patches = [m.group(0) for s in _strings(ti) for m in PATCH_RE.finditer(s)]
    if patches:
        host = "codex"
        for p in patches:
            writes.extend(parse_apply_patch(p))
    else:
        host = "claude"
        fp = ti.get("file_path") or ti.get("path")
        if isinstance(fp, str) and fp:
            if isinstance(ti.get("content"), str):
                writes.append(Write(fp, ti["content"], True))
            elif isinstance(ti.get("new_string"), str):
                writes.append(Write(fp, ti["new_string"], False))
            elif isinstance(ti.get("edits"), list):
                parts = [e.get("new_string", "") for e in ti["edits"] if isinstance(e, dict)]
                writes.append(Write(fp, "\n".join(p for p in parts if isinstance(p, str)), False))
            else:
                writes.append(Write(fp, "", False))
    for w in writes:
        p = w.path if os.path.isabs(w.path) else os.path.join(cwd, w.path)
        w.path = os.path.realpath(p)
    return Event(host, name, session, cwd, tool, writes)


def repo_root(path: str) -> str:
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    try:
        out = subprocess.run(["git", "-C", d or "/", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return os.path.realpath(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def rel_to(path: str, root: str) -> str:
    if root and (path == root or path.startswith(root.rstrip("/") + "/")):
        return os.path.relpath(path, root)
    return path.lstrip("/")


def glob_regex(glob: str) -> re.Pattern:
    """'**/' is zero or more directories, '**' anything, '*' and '?' stay inside one segment."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        elif glob[i] == "{" and "}" in glob[i:]:
            j = glob.index("}", i)
            out.append("(?:" + "|".join(re.escape(x) for x in glob[i + 1:j].split(",")) + ")")
            i = j + 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(glob: str, rel: str) -> bool:
    return bool(glob_regex(glob).match(rel))


# ------------------------------------------------------------------ packs

class Pack:
    def __init__(self, directory: Path, manifest: dict):
        self.dir = directory
        self.stack = manifest["stack"]
        self.files = list(manifest.get("files") or [])
        self.exclude = list(manifest.get("exclude") or [])
        self.lint = manifest.get("lint")
        self._guard = None

    def covers(self, rel: str) -> bool:
        return (any(glob_match(g, rel) for g in self.files)
                and not any(glob_match(g, rel) for g in self.exclude))

    def guard_rules(self):
        """The pack's guard.json rules. Raises ValueError when it cannot be read."""
        if self._guard is None:
            path = self.dir / "guard.json"
            if not path.exists():
                self._guard = []
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                rules = data.get("rules") if isinstance(data, dict) else None
                if not isinstance(rules, list):
                    raise ValueError(f"{path}: no rules list")
                self._guard = rules
        return self._guard


def _version_key(name: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-+]", name)]


def _candidates():
    env = os.environ.get("ORCHID_PACKS")
    if env:
        for entry in env.split(os.pathsep):
            p = Path(entry)
            if (p / "pack.json").is_file():
                yield p
            else:
                yield from sorted(q.parent for q in p.glob("convention-*/pack.json"))
        return
    yield from sorted(q.parent for q in CORE_ROOT.parent.glob("convention-*/pack.json"))
    # Plugin cache: <marketplace>/<plugin>/<version>/; prefer the highest version.
    for plugin in sorted(CORE_ROOT.parent.parent.glob("convention-*")):
        versions = [q.parent for q in plugin.glob("*/pack.json")]
        if versions:
            yield max(versions, key=lambda v: _version_key(v.name))


def discover_packs():
    """Return (packs, problems). The first pack found for a stack wins."""
    packs, problems, seen = [], [], set()
    for d in _candidates():
        try:
            manifest = json.loads((d / "pack.json").read_text(encoding="utf-8"))
            stack = manifest["stack"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            problems.append(f"pack at {d} is unreadable ({e}); its rules were not applied")
            continue
        if stack in seen:
            continue
        seen.add(stack)
        packs.append(Pack(d, manifest))
    return packs, problems


# ------------------------------------------------------------- repo tier

def repo_overrides(root: str, stack: str) -> dict:
    """Rule ids the repo switched off in .orchid/conventions/<stack>.md, with reasons.

    A block counts only with both 'override: global' and a non-empty 'reason:'.
    Headings of any depth are read; only a heading that is a rule id opens a block.
    """
    path = Path(root or ".") / ".orchid" / "conventions" / f"{stack}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out, current, fields = {}, None, {}

    def close():
        if current and fields.get("override") == "global" and fields.get("reason"):
            out[current] = fields["reason"]

    for line in text.split("\n"):
        m = re.match(r"^#+\s+`?([^\s`]+)`?\s*$", line)
        if m:
            close()
            current = m.group(1) if ID_RE.match(m.group(1)) else None
            fields = {}
            continue
        m = re.match(r"^\s*(override|reason):\s*(.*?)\s*$", line)
        if m and current:
            fields[m.group(1)] = m.group(2)
    close()
    return out


# ------------------------------------------------------------------ state

class State:
    """Per-repo hook state, kept outside the work tree.

    Lives in the repository's git dir (never committed, never in git status),
    or ORCHID_STATE_DIR when set. Outside git there is no safe place, so state
    is unavailable and callers must say so rather than pretend.
    """

    def __init__(self, root: str):
        self.dir = None
        env = os.environ.get("ORCHID_STATE_DIR")
        if env:
            self.dir = Path(env)
        elif root:
            try:
                out = subprocess.run(["git", "-C", root, "rev-parse", "--absolute-git-dir"],
                                     capture_output=True, text=True, timeout=5)
                if out.returncode == 0 and out.stdout.strip():
                    self.dir = Path(out.stdout.strip()) / "orchid-convention"
            except (OSError, subprocess.SubprocessError):
                self.dir = None
        if self.dir is not None:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.dir = None

    @property
    def available(self) -> bool:
        return self.dir is not None

    def update(self, name: str, fn):
        """Read-modify-write one JSON file under an exclusive lock; returns fn's result."""
        if self.dir is None:
            return None
        path = self.dir / name
        try:
            with open(self.dir / (name + ".lock"), "a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except (OSError, ValueError):
                    data = {}
                result = fn(data)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
                os.replace(tmp, path)
                return result
        except OSError:
            return None

    def once(self, session: str, key: str) -> bool:
        """True the first time key is seen this session, and always when state is unavailable."""
        def fn(data):
            seen = data.setdefault(session, {"t": 0, "keys": []})
            seen["t"] = int(time.time())
            if key in seen["keys"]:
                return False
            seen["keys"].append(key)
            _prune(data)
            return True
        result = self.update("notices.json", fn)
        return True if result is None else result

    def note(self, name: str, text):
        """Write (or with None, remove) a degraded-capability note for the gate to surface."""
        if self.dir is None:
            return
        d = self.dir / "degraded"
        try:
            if text is None:
                (d / name).unlink()
            else:
                d.mkdir(exist_ok=True)
                (d / name).write_text(text, encoding="utf-8")
        except OSError:
            pass


def _prune(data: dict, keep: int = 32):
    if len(data) > keep:
        for s in sorted(data, key=lambda k: data[k].get("t", 0) if isinstance(data[k], dict) else 0)[:-keep]:
            del data[s]


def emit(obj: dict):
    if obj:
        print(json.dumps(obj))
