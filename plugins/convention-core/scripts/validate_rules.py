#!/usr/bin/env python3
"""Validate every convention pack in a checkout. Python 3.9+ standard library only.

Usage: validate_rules.py [--root <checkout>] [--quiet]

A pack is plugins/convention-<stack>/ holding pack.json. For each pack this checks:

  1. pack.json: stack id, file globs, and a lint declaration (or an explicit null).
  2. Every rules/<id>.md frontmatter against schema/rule.schema.json.
  3. Id == file name, id prefix == stack == directory, ids unique across packs.
  4. guard.json holds exactly the fragment-safe regex rules that are not inert,
     and mirrors each one's pattern, flags, globs, exclusion, overridability
     and severity. A guard entry that drifts from its rule is a guard and a
     scanner that disagree about what the rule is.
  5. Every regex is portable ERE: grep -E accepts it, and it avoids escapes
     BSD and GNU grep treat differently.
  6. A regex rule's examples behave: each bad example matches, no good one does.
  7. Every rule has fixtures/<id>.cases with at least one good case and one bad
     case that expects it.
  8. A lint rule's lint_rule_id appears in the pack's bundled linter config.

The YAML reader handles the frontmatter subset the rules use (mappings, block
and flow lists, quoted and plain scalars, | and > block scalars) and rejects
anything else. The schema checker implements the draft-07 keywords the schema
uses and fails on any other keyword, so an unenforced schema line cannot pass.

Exit 0 when everything holds, 1 on any failure, 2 on a usage or setup error.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9]*-[a-z]+-[0-9]{3}$")
DATE_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")

# Escapes that BSD grep (macOS) and GNU grep read differently or reject.
NON_PORTABLE = (
    ("(?", "lookaround or inline flags; use the rule's flags field"),
    ("\\d", "use [0-9]"),
    ("\\w", "use [A-Za-z0-9_]"),
    ("\\W", "use [^A-Za-z0-9_]"),
    ("\\s", "use [[:space:]]"),
    ("\\S", "use [^[:space:]]"),
    ("\\b", "use ([^A-Za-z0-9_]|^) or ([^A-Za-z0-9_]|$)"),
    ("\\B", "not portable"),
    ("\\<", "not portable; use an explicit boundary class"),
    ("\\>", "not portable; use an explicit boundary class"),
)


class YamlError(ValueError):
    pass


# ---------------------------------------------------------------- YAML subset

def _strip_comment(s: str) -> str:
    if s.startswith("#"):
        return ""
    idx = s.find(" #")
    return s[:idx].rstrip() if idx >= 0 else s


def _unquote(raw: str, where: str):
    s = raw.strip()
    if not s:
        return None
    if s[0] == '"':
        if len(s) < 2 or s[-1] != '"':
            raise YamlError(f"{where}: unterminated double-quoted string")
        body = s[1:-1]
        out = []
        i = 0
        escapes = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "/": "/", "0": "\0"}
        while i < len(body):
            c = body[i]
            if c == "\\":
                if i + 1 >= len(body) or body[i + 1] not in escapes:
                    raise YamlError(f"{where}: unsupported escape in double-quoted string")
                out.append(escapes[body[i + 1]])
                i += 2
                continue
            if c == '"':
                raise YamlError(f"{where}: unescaped quote inside double-quoted string")
            out.append(c)
            i += 1
        return "".join(out)
    if s[0] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise YamlError(f"{where}: unterminated single-quoted string")
        body = s[1:-1]
        if "'" in body.replace("''", ""):
            raise YamlError(f"{where}: unescaped quote inside single-quoted string")
        return body.replace("''", "'")
    s = _strip_comment(s)
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    if re.fullmatch(r"-?[0-9]+", s):
        return int(s)
    if s[0] in "&*!|>@`{%":
        raise YamlError(f"{where}: unsupported YAML construct '{s[0]}'")
    if ": " in s:
        raise YamlError(f"{where}: plain scalar contains ': '; quote it")
    return s


def _split_flow(body: str, where: str):
    items, cur, quote, i = [], [], None, 0
    while i < len(body):
        c = body[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(body):
                cur.append(body[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            cur.append(c)
        elif c == ",":
            items.append("".join(cur))
            cur = []
        elif c in "[]{}":
            raise YamlError(f"{where}: nested flow collections are not supported")
        else:
            cur.append(c)
        i += 1
    if quote:
        raise YamlError(f"{where}: unterminated string in flow list")
    tail = "".join(cur)
    if tail.strip():
        items.append(tail)
    return [_unquote(x, where) for x in items]


def _scalar(raw: str, where: str):
    s = raw.strip()
    if s.startswith("["):
        s = _strip_comment(s) if not s.endswith("]") else s
        if not s.endswith("]"):
            raise YamlError(f"{where}: unterminated flow list")
        return _split_flow(s[1:-1], where)
    return _unquote(s, where)


def parse_yaml(text: str, origin: str = "<yaml>"):
    lines = text.split("\n")
    pos = [0]

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def significant(i: int) -> bool:
        stripped = lines[i].strip()
        return bool(stripped) and not stripped.startswith("#")

    def next_sig(i: int) -> int:
        while i < len(lines) and not significant(i):
            i += 1
        return i

    def block_scalar(header: str, parent_indent: int, where: str) -> str:
        style, chomp = header[0], header[1:]
        if chomp not in ("", "-"):
            raise YamlError(f"{where}: unsupported block scalar header '{header}'")
        body, block_indent = [], None
        while pos[0] < len(lines):
            line = lines[pos[0]]
            if line.strip() == "":
                body.append("")
                pos[0] += 1
                continue
            ind = indent_of(line)
            if ind <= parent_indent:
                break
            if block_indent is None:
                block_indent = ind
            if ind < block_indent:
                raise YamlError(f"{where}: inconsistent block scalar indentation")
            body.append(line[block_indent:])
            pos[0] += 1
        while body and body[-1] == "":
            body.pop()
        if style == "|":
            out = "\n".join(body)
        else:
            paras, cur = [], []
            for b in body:
                if b == "":
                    paras.append(" ".join(cur))
                    cur = []
                else:
                    cur.append(b.strip())
            paras.append(" ".join(cur))
            out = "\n".join(paras)
        return out if chomp == "-" else out + "\n"

    def parse_block(indent: int):
        i = next_sig(pos[0])
        if i >= len(lines):
            return None
        first = lines[i]
        if indent_of(first) != indent:
            raise YamlError(f"{origin}:{i + 1}: unexpected indentation")
        if "\t" in first[: indent + 1]:
            raise YamlError(f"{origin}:{i + 1}: tab indentation is not supported")
        if first.strip().startswith("- ") or first.strip() == "-":
            return parse_list(indent)
        return parse_map(indent)

    def value_after(rest: str, indent: int, where: str):
        rest = rest.strip()
        if rest in ("", "#") or rest.startswith("# "):
            j = next_sig(pos[0])
            if j < len(lines) and indent_of(lines[j]) > indent:
                return parse_block(indent_of(lines[j]))
            if j < len(lines) and indent_of(lines[j]) == indent and lines[j].strip().startswith("- "):
                return parse_list(indent)
            return None
        if rest[0] in "|>":
            return block_scalar(rest, indent, where)
        return _scalar(rest, where)

    def parse_map(indent: int) -> dict:
        out = {}
        while True:
            i = next_sig(pos[0])
            if i >= len(lines) or indent_of(lines[i]) < indent:
                pos[0] = i
                return out
            line = lines[i]
            where = f"{origin}:{i + 1}"
            if indent_of(line) > indent:
                raise YamlError(f"{where}: unexpected indentation")
            m = re.match(r"^( *)([A-Za-z_][A-Za-z0-9_-]*):(?: (.*)|)$", line.rstrip())
            if not m:
                raise YamlError(f"{where}: expected 'key: value'")
            key = m.group(2)
            if key in out:
                raise YamlError(f"{where}: duplicate key '{key}'")
            pos[0] = i + 1
            out[key] = value_after(m.group(3) or "", indent, where)

    def parse_list(indent: int) -> list:
        out = []
        while True:
            i = next_sig(pos[0])
            if i >= len(lines) or indent_of(lines[i]) < indent:
                pos[0] = i
                return out
            line = lines[i]
            where = f"{origin}:{i + 1}"
            stripped = line.strip()
            if indent_of(line) != indent or not (stripped.startswith("- ") or stripped == "-"):
                pos[0] = i
                return out
            item = stripped[1:].strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:( |$)", item):
                raise YamlError(f"{where}: mappings inside lists are not supported")
            pos[0] = i + 1
            if item and item[0] in "|>":
                out.append(block_scalar(item, indent, where))
            else:
                out.append(_scalar(item, where))

    result = parse_block(0)
    tail = next_sig(pos[0])
    if tail < len(lines):
        raise YamlError(f"{origin}:{tail + 1}: unparsed content")
    return result if result is not None else {}


def read_frontmatter(path: Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise YamlError(f"{path}: must start with a '---' frontmatter line")
    end = text.find("\n---\n", 4)
    if end < 0 and text.endswith("\n---"):
        end = len(text) - 4
    if end < 0:
        raise YamlError(f"{path}: frontmatter is not closed by a '---' line")
    data = parse_yaml(text[4:end + 1], str(path))
    if not isinstance(data, dict):
        raise YamlError(f"{path}: frontmatter must be a mapping")
    return data, text[end + 5:]


# ------------------------------------------------------- draft-07 subset

SUPPORTED_KEYWORDS = {
    "$schema", "$id", "title", "description", "type", "properties", "required",
    "additionalProperties", "enum", "const", "pattern", "minLength", "maxLength",
    "minItems", "items", "minimum", "format", "allOf", "if", "then",
}

TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def unsupported_keywords(schema, path: str = "#"):
    """Every keyword anywhere in the schema that schema_errors does not enforce."""
    if not isinstance(schema, dict):
        return
    for key in sorted(set(schema) - SUPPORTED_KEYWORDS):
        yield f"{path}: unsupported keyword '{key}'"
    if "type" in schema and schema["type"] not in TYPES:
        yield f"{path}: unsupported type {schema['type']!r}"
    for key, sub in schema.get("properties", {}).items():
        yield from unsupported_keywords(sub, f"{path}/properties/{key}")
    for key in ("items", "if", "then"):
        if key in schema:
            yield from unsupported_keywords(schema[key], f"{path}/{key}")
    for i, sub in enumerate(schema.get("allOf", [])):
        yield from unsupported_keywords(sub, f"{path}/allOf/{i}")


def schema_errors(schema: dict, value, path: str = ""):
    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        yield f"{path or '/'}: schema uses unsupported keyword(s) {sorted(unknown)}"
        return
    where = path or "/"
    if "type" in schema:
        check = TYPES.get(schema["type"])
        if check is None:
            yield f"{where}: schema uses unsupported type {schema['type']!r}"
            return
        if not check(value):
            yield f"{where}: expected {schema['type']}, got {type(value).__name__}"
            return
    if "const" in schema and value != schema["const"]:
        yield f"{where}: must be {json.dumps(schema['const'])}"
    if "enum" in schema and value not in schema["enum"]:
        yield f"{where}: {value!r} is not one of {schema['enum']}"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            yield f"{where}: shorter than {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            yield f"{where}: longer than {schema['maxLength']}"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            yield f"{where}: {value!r} does not match {schema['pattern']}"
        if schema.get("format") == "date" and not DATE_RE.match(value):
            yield f"{where}: {value!r} is not a YYYY-MM-DD date"
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            yield f"{where}: below minimum {schema['minimum']}"
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            yield f"{where}: needs at least {schema['minItems']} item(s)"
        if "items" in schema:
            for i, item in enumerate(value):
                yield from schema_errors(schema["items"], item, f"{path}/{i}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                yield f"{where}: missing required '{key}'"
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                yield from schema_errors(sub, value[key], f"{path}/{key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    yield f"{where}: unexpected property '{key}'"
    for sub in schema.get("allOf", []):
        if "if" in sub:
            matched = not list(schema_errors(sub["if"], value, path))
            if matched and "then" in sub:
                yield from schema_errors(sub["then"], value, path)
        else:
            yield from schema_errors(sub, value, path)


# ------------------------------------------------------------ fixture cases

def parse_cases(text: str, origin: str = "<cases>"):
    """Parse a .cases file into a list of case dicts.

    A case starts with '#> case good: <title>' or '#> case bad: <title>' and is
    followed by '#> path: <repo-relative path>' (required), '#> expect: <ids>'
    (required for bad), and optionally '#> tool: Write|Edit'. Every other line
    up to the next case header is the case body.
    """
    cases, cur = [], None
    for n, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^#> case (good|bad): (.+)$", line)
        if m:
            cur = {"kind": m.group(1), "title": m.group(2).strip(), "path": None,
                   "expect": [], "tool": "Write", "body": [], "line": n}
            cases.append(cur)
            continue
        if line.startswith("#> "):
            if cur is None:
                raise ValueError(f"{origin}:{n}: directive before the first case")
            if cur["body"]:
                raise ValueError(f"{origin}:{n}: directives must come before the case body")
            key, _, val = line[3:].partition(":")
            key, val = key.strip(), val.strip()
            if key == "path":
                cur["path"] = val
            elif key == "expect":
                cur["expect"] = val.split()
            elif key == "tool":
                if val not in ("Write", "Edit"):
                    raise ValueError(f"{origin}:{n}: tool must be Write or Edit")
                cur["tool"] = val
            else:
                raise ValueError(f"{origin}:{n}: unknown directive '{key}'")
            continue
        if cur is None:
            if line.strip():
                raise ValueError(f"{origin}:{n}: text before the first case")
            continue
        cur["body"].append(line)
    for c in cases:
        while c["body"] and c["body"][-1] == "":
            c["body"].pop()
        c["body"] = "\n".join(c["body"]) + "\n"
        where = f"{origin}:{c['line']}"
        if not c["path"]:
            raise ValueError(f"{where}: case has no '#> path:'")
        if c["path"].startswith("/") or ".." in c["path"].split("/"):
            raise ValueError(f"{where}: path must be repo-relative")
        if c["kind"] == "bad" and not c["expect"]:
            raise ValueError(f"{where}: bad case has no '#> expect:'")
        if c["kind"] == "good" and c["expect"]:
            raise ValueError(f"{where}: good case must not carry '#> expect:'")
        for rid in c["expect"]:
            if not ID_RE.match(rid):
                raise ValueError(f"{where}: '{rid}' is not a rule id")
        if not c["body"].strip():
            raise ValueError(f"{where}: case body is empty")
    return cases


# ------------------------------------------------------------------ checks

class Report:
    def __init__(self, quiet: bool):
        self.failures = 0
        self.quiet = quiet

    def fail(self, msg: str):
        self.failures += 1
        print(f"FAIL: {msg}")

    def warn(self, msg: str):
        print(f"WARN: {msg}")

    def ok(self, msg: str):
        if not self.quiet:
            print(f"ok: {msg}")


def grep_lines(pattern: str, text: str, icase: bool):
    """1-based line numbers grep -E matches; raises RuntimeError if grep rejects it."""
    args = ["grep", "-n", "-E"] + (["-i"] if icase else []) + ["--", pattern]
    proc = subprocess.run(args, input=text, capture_output=True, text=True)
    if proc.returncode == 1:
        return set()
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or f"grep exit {proc.returncode}")
    return {int(x.split(":", 1)[0]) for x in proc.stdout.splitlines() if x}


def regex_hits(detect: dict, text: str):
    icase = "i" in detect.get("flags", "")
    hits = grep_lines(detect["pattern"], text, icase)
    if hits and detect.get("exclude_pattern"):
        hits -= grep_lines(detect["exclude_pattern"], text, icase)
    return hits


def check_ere(report: Report, pattern: str, where: str):
    for token, hint in NON_PORTABLE:
        if token in pattern:
            report.fail(f"{where}: pattern uses non-portable '{token}' ({hint})")
    try:
        grep_lines(pattern, "", False)
    except RuntimeError as e:
        report.fail(f"{where}: grep -E rejects the pattern: {e}")


def check_pack_manifest(report: Report, pack_dir: Path, stack_dir: str):
    path = pack_dir / "pack.json"
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        report.fail(f"{path}: unreadable: {e}")
        return None
    if not isinstance(pack, dict):
        report.fail(f"{path}: must be an object")
        return None
    allowed = {"$comment", "stack", "files", "exclude", "lint"}
    for key in sorted(set(pack) - allowed):
        report.fail(f"{path}: unexpected key '{key}'")
    stack = pack.get("stack")
    if stack != stack_dir:
        report.fail(f"{path}: stack {stack!r} must equal the directory suffix {stack_dir!r}")
    for key in ("files", "exclude"):
        val = pack.get(key, [])
        if key == "files" and not val:
            report.fail(f"{path}: 'files' must list at least one glob")
        if not isinstance(val, list) or not all(isinstance(g, str) and g for g in val):
            report.fail(f"{path}: '{key}' must be a list of non-empty globs")
    if "lint" not in pack:
        report.fail(f"{path}: declare 'lint' (an object, or null for a stack with no linter)")
    lint = pack.get("lint")
    if lint is not None:
        if not isinstance(lint, dict):
            report.fail(f"{path}: 'lint' must be an object or null")
            return pack
        for key in sorted(set(lint) - {"tool", "args", "config", "missing", "timeout"}):
            report.fail(f"{path}: lint has unexpected key '{key}'")
        if not isinstance(lint.get("tool"), str) or not lint.get("tool") or "/" in lint.get("tool", ""):
            report.fail(f"{path}: lint.tool must be a bare executable name")
        args = lint.get("args")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            report.fail(f"{path}: lint.args must be a list of strings")
        elif "{file}" not in args:
            report.fail(f"{path}: lint.args must pass the file as a separate '{{file}}' argument")
        if not isinstance(lint.get("missing"), str) or not lint.get("missing"):
            report.fail(f"{path}: lint.missing must say how to install the linter")
        if "timeout" in lint and not (isinstance(lint["timeout"], int) and 1 <= lint["timeout"] <= 55):
            report.fail(f"{path}: lint.timeout must be an integer from 1 to 55 seconds")
        config = lint.get("config")
        if config is not None:
            if not isinstance(config, dict) or set(config) != {"file", "args"}:
                report.fail(f"{path}: lint.config must be {{\"file\": ..., \"args\": [...]}}")
            elif "{config}" not in config["args"] or not isinstance(args, list) or "{config_args}" not in args:
                report.fail(f"{path}: lint.config.args needs '{{config}}' and lint.args needs '{{config_args}}'")
    return pack


def check_rules(report: Report, pack_dir: Path, stack: str, schema: dict, seen: dict):
    rules = {}
    rules_dir = pack_dir / "rules"
    for path in sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []:
        try:
            fm, _ = read_frontmatter(path)
        except (YamlError, OSError, UnicodeDecodeError) as e:
            report.fail(str(e))
            continue
        errs = list(schema_errors(schema, fm))
        for err in errs:
            report.fail(f"{path}: {err}")
        rid = fm.get("id")
        if not isinstance(rid, str):
            continue
        if path.stem != rid:
            report.fail(f"{path}: file name must be '{rid}.md'")
        if fm.get("stack") != stack or not rid.startswith(stack + "-"):
            report.fail(f"{path}: stack and id prefix must be '{stack}'")
        if rid.split("-")[1:2] != [fm.get("category")]:
            report.fail(f"{path}: id category part must equal category {fm.get('category')!r}")
        if rid in seen:
            report.fail(f"{path}: duplicate rule id, also in {seen[rid]}")
        seen[rid] = path
        if not errs:
            rules[rid] = fm
            report.ok(f"{rid}: schema")
    return rules


def is_inert(rule: dict) -> bool:
    return rule.get("state") in ("proposed", "removed")


def check_guard(report: Report, pack_dir: Path, stack: str, rules: dict):
    path = pack_dir / "guard.json"
    wanted = sorted(rid for rid, r in rules.items()
                    if r["detect"]["method"] == "regex" and r["detect"]["fragment_safe"] and not is_inert(r))
    if not path.exists():
        if wanted:
            report.fail(f"{path}: missing, but fragment-safe rules exist: {wanted}")
        return
    try:
        guard = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        report.fail(f"{path}: unreadable: {e}")
        return
    if not isinstance(guard, dict) or guard.get("stack") != stack or not isinstance(guard.get("rules"), list):
        report.fail(f"{path}: must be {{\"stack\": \"{stack}\", \"rules\": [...]}}")
        return
    allowed = {"id", "pattern", "flags", "file_glob", "exclude_glob", "exclude_pattern",
               "severity", "overridable", "message"}
    listed = []
    before = report.failures
    for entry in guard["rules"]:
        rid = entry.get("id") if isinstance(entry, dict) else None
        where = f"{path}: {rid}"
        if not isinstance(rid, str):
            report.fail(f"{path}: every entry needs an id")
            continue
        listed.append(rid)
        for key in sorted(set(entry) - allowed):
            report.fail(f"{where}: unexpected key '{key}'")
        for key in ("pattern", "file_glob", "severity", "overridable", "message"):
            if key not in entry:
                report.fail(f"{where}: missing '{key}' (the engine never defaults it)")
        if not isinstance(entry.get("message"), str) or not entry.get("message", "").strip():
            report.fail(f"{where}: message must be a non-empty string")
        rule = rules.get(rid)
        if rule is None:
            report.fail(f"{where}: no valid rules/{rid}.md")
            continue
        det = rule["detect"]
        if det["method"] != "regex" or det["fragment_safe"] is not True:
            report.fail(f"{where}: only fragment-safe regex rules may be guarded")
            continue
        if is_inert(rule):
            report.fail(f"{where}: rule state {rule['state']!r} is inert and must not be guarded")
        for key in ("pattern", "flags", "file_glob", "exclude_glob", "exclude_pattern"):
            if entry.get(key, "") != det.get(key, ""):
                report.fail(f"{where}: {key} {entry.get(key)!r} differs from the rule's {det.get(key)!r}")
        if entry.get("overridable") is not rule["overridable"]:
            report.fail(f"{where}: overridable must mirror the rule ({rule['overridable']})")
        sev = entry.get("severity")
        if sev not in ("block", "warn"):
            report.fail(f"{where}: severity must be 'block' or 'warn'")
        effective = "block" if rule["state"] == "active" and rule["severity"] == "block" else "warn"
        if sev != effective:
            report.fail(f"{where}: severity must be {effective!r} for a {rule['state']} {rule['severity']} rule")
    if len(listed) != len(set(listed)):
        report.fail(f"{path}: duplicate ids")
    for rid in wanted:
        if rid not in listed:
            report.fail(f"{path}: fragment-safe regex rule {rid} is not guarded")
    if listed and report.failures == before:
        report.ok(f"{stack}: guard.json mirrors {len(listed)} rule(s)")


def check_regex_rules(report: Report, rules: dict):
    for rid, rule in sorted(rules.items()):
        det = rule["detect"]
        for key in ("pattern", "exclude_pattern"):
            if key in det:
                check_ere(report, det[key], f"{rid} detect.{key}")
        if det["method"] != "regex":
            continue
        try:
            for ex in rule["examples"]["bad"]:
                if not regex_hits(det, ex):
                    report.fail(f"{rid}: bad example does not match the pattern: {ex!r}")
            for ex in rule["examples"]["good"]:
                if regex_hits(det, ex):
                    report.fail(f"{rid}: good example matches the pattern: {ex!r}")
        except RuntimeError as e:
            report.fail(f"{rid}: pattern could not be evaluated: {e}")


def check_fixtures(report: Report, pack_dir: Path, rules: dict):
    fixtures = pack_dir / "fixtures"
    known = set(rules)
    for path in sorted(fixtures.glob("*.cases")) if fixtures.is_dir() else []:
        if path.stem not in known:
            report.fail(f"{path}: no rule named {path.stem}")
    for rid in sorted(rules):
        path = fixtures / f"{rid}.cases"
        if not path.exists():
            report.fail(f"{rid}: missing fixtures/{rid}.cases (every rule ships good and bad fixtures)")
            continue
        try:
            cases = parse_cases(path.read_text(encoding="utf-8"), str(path))
        except (ValueError, OSError) as e:
            report.fail(str(e))
            continue
        good = [c for c in cases if c["kind"] == "good"]
        bad = [c for c in cases if c["kind"] == "bad" and rid in c["expect"]]
        if not good or not bad:
            report.fail(f"{path}: needs a good case and a bad case expecting {rid}")
        for c in cases:
            for other in c["expect"]:
                if other not in known:
                    report.fail(f"{path}:{c['line']}: expects unknown rule {other}")
        if good and bad:
            report.ok(f"{rid}: {len(good)} good / {len(bad)} bad fixture case(s)")


def check_lint_rules(report: Report, pack_dir: Path, pack: dict, rules: dict):
    lint_rules = {rid: r for rid, r in rules.items() if r["detect"]["method"] == "lint"}
    if not lint_rules:
        return
    lint = pack.get("lint") if isinstance(pack, dict) else None
    if not lint:
        report.fail(f"{pack_dir}: lint rules {sorted(lint_rules)} but pack.json declares no linter")
        return
    config = lint.get("config") or {}
    cfg_path = pack_dir / config.get("file", "") if config.get("file") else None
    if cfg_path is None or not cfg_path.is_file():
        report.fail(f"{pack_dir}: lint rules need the bundled linter config named in lint.config.file")
        return
    text = cfg_path.read_text(encoding="utf-8")
    for rid, rule in sorted(lint_rules.items()):
        lid = rule["detect"]["lint_rule_id"]
        if not re.search(r"(^|[^A-Za-z0-9_])" + re.escape(lid) + r"([^A-Za-z0-9_]|$)", text):
            report.fail(f"{rid}: lint_rule_id {lid!r} does not appear in {cfg_path.name}")


def check_id_history(report: Report, root: Path, live: set):
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--diff-filter=D", "--name-only", "--pretty=format:",
             "--", "plugins/*/rules/*.md"],
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        report.warn("git history unavailable; rule-file deletion was not checked")
        return
    for line in sorted(set(x.strip() for x in out.splitlines() if x.strip())):
        rid = Path(line).stem
        if rid not in live:
            report.fail(f"rule file {line} was deleted; keep it with state 'removed' so the id is never reused")


def main(argv) -> int:
    root = Path(__file__).resolve().parents[3]
    quiet = False
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--root" and args:
            root = Path(args.pop(0)).resolve()
        elif a == "--quiet":
            quiet = True
        else:
            print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
            return 2
    schema_path = root / "plugins" / "convention-core" / "schema" / "rule.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"validate_rules.py: cannot read {schema_path}: {e}", file=sys.stderr)
        return 2
    report = Report(quiet)
    for problem in unsupported_keywords(schema):
        report.fail(f"{schema_path}: {problem}")
    seen: dict = {}
    packs = []
    for pack_dir in sorted((root / "plugins").glob("convention-*")):
        if pack_dir.name == "convention-core" or not pack_dir.is_dir():
            continue
        stack = pack_dir.name[len("convention-"):]
        if not (pack_dir / "pack.json").exists():
            if (pack_dir / "rules").exists():
                report.fail(f"{pack_dir}: has rules but no pack.json")
            else:
                report.warn(f"{pack_dir}: no pack.json yet; nothing to validate")
            continue
        packs.append(stack)
        pack = check_pack_manifest(report, pack_dir, stack)
        rules = check_rules(report, pack_dir, stack, schema, seen)
        check_guard(report, pack_dir, stack, rules)
        check_regex_rules(report, rules)
        check_fixtures(report, pack_dir, rules)
        check_lint_rules(report, pack_dir, pack, rules)
    check_id_history(report, root, set(seen))
    if report.failures:
        print(f"FAILED: {report.failures} problem(s).")
        return 1
    print(f"OK: {len(packs)} pack(s), {len(seen)} rule(s) validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
