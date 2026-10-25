"""Behaviour tests for plugins/convention-core/scripts/validate_rules.py.

Each test builds a throwaway checkout holding the real schema and a small
'demo' pack, breaks one thing, and asserts the validator names it. The
validator gates every rule change, so a check that stops firing here is a
check that stops protecting the packs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "plugins" / "convention-core"
VALIDATOR = CORE / "scripts" / "validate_rules.py"

sys.path.insert(0, str(CORE / "scripts"))
import validate_rules as vr  # noqa: E402

REGEX_RULE = """---
id: demo-naming-001
stack: demo
category: naming
title: Do not name things Foo
statement: Identifiers must not be called Foo.
rationale: Foo says nothing.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])Foo([^A-Za-z0-9_]|$)"
  file_glob: "**/*.demo"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "let bar = 1"
    - "// Foo in a comment"
  bad:
    - "let Foo = 1"
fix: Pick a real name.
tags: [naming, "demo"]
---

Body text.
"""

MODEL_RULE = """---
id: demo-security-001
stack: demo
category: security
title: Keep secrets out of logs
statement: >
  Log calls must not carry
  credentials.
rationale: |
  Logs travel further
  than code.
state: active
overridable: false
ignorable: false
scope: full-repo
severity: block
introduced: 2026-10-25
detect:
  method: model
  file_glob: "**/*.demo"
  fragment_safe: false
examples:
  good:
    - "log(user.id)"
  bad:
    - "log(user.password)"
---
"""

GUARD = {
    "stack": "demo",
    "rules": [{
        "id": "demo-naming-001",
        "pattern": "(^|[^A-Za-z0-9_])Foo([^A-Za-z0-9_]|$)",
        "file_glob": "**/*.demo",
        "exclude_pattern": "^[[:space:]]*//",
        "severity": "block",
        "overridable": True,
        "message": "Do not name things Foo.",
    }],
}

PACK = {
    "stack": "demo",
    "files": ["**/*.demo"],
    "lint": {"tool": "demolint", "args": ["{config_args}", "{file}"],
             "config": {"file": "demolint.cfg", "args": ["--config", "{config}"]},
             "missing": "install demolint"},
}

CASES = {
    "demo-naming-001": "#> case good: plain name\n#> path: src/a.demo\nlet bar = 1\n"
                       "#> case bad: Foo\n#> path: src/a.demo\n#> expect: demo-naming-001\nlet Foo = 1\n",
    "demo-security-001": "#> case good: id\n#> path: src/a.demo\nlog(user.id)\n"
                         "#> case bad: password\n#> path: src/a.demo\n#> expect: demo-security-001\n"
                         "log(user.password)\n",
}


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orchid-validate-"))
        (self.root / "plugins" / "convention-core" / "schema").mkdir(parents=True)
        shutil.copy(CORE / "schema" / "rule.schema.json", self.root / "plugins/convention-core/schema/")
        self.pack = self.root / "plugins" / "convention-demo"
        (self.pack / "rules").mkdir(parents=True)
        (self.pack / "fixtures").mkdir()
        self.write("rules/demo-naming-001.md", REGEX_RULE)
        self.write("rules/demo-security-001.md", MODEL_RULE)
        self.write_json("guard.json", GUARD)
        self.write_json("pack.json", PACK)
        self.write("demolint.cfg", "rules: []\n")
        for rid, text in CASES.items():
            self.write(f"fixtures/{rid}.cases", text)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text):
        (self.pack / rel).write_text(text, encoding="utf-8")

    def write_json(self, rel, obj):
        self.write(rel, json.dumps(obj, indent=2))

    def run_validator(self):
        proc = subprocess.run([sys.executable, str(VALIDATOR), "--root", str(self.root), "--quiet"],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def assert_fails(self, needle):
        code, out = self.run_validator()
        self.assertEqual(code, 1, out)
        self.assertIn(needle, out)

    def test_valid_pack_passes(self):
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)
        self.assertIn("1 pack(s), 2 rule(s)", out)

    def test_yaml_subset(self):
        fm, body = vr.read_frontmatter(self.pack / "rules" / "demo-security-001.md")
        self.assertEqual(fm["statement"], "Log calls must not carry credentials.\n")
        self.assertEqual(fm["rationale"], "Logs travel further\nthan code.\n")
        self.assertIs(fm["overridable"], False)
        fm, _ = vr.read_frontmatter(self.pack / "rules" / "demo-naming-001.md")
        self.assertEqual(fm["tags"], ["naming", "demo"])
        self.assertEqual(fm["detect"]["pattern"], "(^|[^A-Za-z0-9_])Foo([^A-Za-z0-9_]|$)")
        self.assertEqual(vr.parse_yaml("a: 'it''s'\nb: \"x\\\\y\"\n"), {"a": "it's", "b": "x\\y"})
        for bad in ("a: &anchor x\n", "a: b: c\n", "a: 1\na: 2\n", "a: \"\\q\"\n", "- k: v\n"):
            with self.assertRaises(vr.YamlError, msg=bad):
                vr.parse_yaml(bad)

    def test_schema_violations(self):
        self.write("rules/demo-naming-001.md", REGEX_RULE.replace("state: active\n", "state: live\n"))
        self.assert_fails("'live' is not one of")

    def test_non_overridable_must_not_be_ignorable(self):
        self.write("rules/demo-security-001.md", MODEL_RULE.replace("ignorable: false", "ignorable: true"))
        self.assert_fails("/ignorable: must be false")

    def test_model_rule_cannot_be_fragment_safe(self):
        self.write("rules/demo-security-001.md",
                   MODEL_RULE.replace("fragment_safe: false", "fragment_safe: true"))
        self.assert_fails("/detect/fragment_safe: must be false")

    def test_unknown_property(self):
        self.write("rules/demo-naming-001.md", REGEX_RULE.replace("tags:", "owner: me\ntags:"))
        self.assert_fails("unexpected property 'owner'")

    def test_filename_must_match_id(self):
        (self.pack / "rules" / "demo-naming-001.md").rename(self.pack / "rules" / "demo-naming-002.md")
        self.assert_fails("file name must be 'demo-naming-001.md'")

    def test_guard_pattern_drift(self):
        guard = json.loads(json.dumps(GUARD))
        guard["rules"][0]["pattern"] = "Foo"
        self.write_json("guard.json", guard)
        self.assert_fails("pattern 'Foo' differs")

    def test_guard_overridable_must_be_explicit_and_mirror(self):
        guard = json.loads(json.dumps(GUARD))
        del guard["rules"][0]["overridable"]
        self.write_json("guard.json", guard)
        self.assert_fails("missing 'overridable'")

    def test_unguarded_fragment_safe_rule(self):
        self.write_json("guard.json", {"stack": "demo", "rules": []})
        self.assert_fails("demo-naming-001 is not guarded")

    def test_model_rule_in_guard(self):
        guard = json.loads(json.dumps(GUARD))
        guard["rules"].append(dict(GUARD["rules"][0], id="demo-security-001", overridable=False))
        self.write_json("guard.json", guard)
        self.assert_fails("only fragment-safe regex rules may be guarded")

    def test_non_portable_regex(self):
        rule = REGEX_RULE.replace("(^|[^A-Za-z0-9_])Foo([^A-Za-z0-9_]|$)", "\\\\bFoo\\\\b")
        self.write("rules/demo-naming-001.md", rule)
        guard = json.loads(json.dumps(GUARD))
        guard["rules"][0]["pattern"] = "\\bFoo\\b"
        self.write_json("guard.json", guard)
        self.assert_fails("non-portable '\\b'")

    def test_bad_example_must_match(self):
        self.write("rules/demo-naming-001.md", REGEX_RULE.replace('"let Foo = 1"', '"let Fo = 1"'))
        self.assert_fails("bad example does not match")

    def test_good_example_must_not_match(self):
        self.write("rules/demo-naming-001.md", REGEX_RULE.replace('"let bar = 1"', '"Foo()"'))
        self.assert_fails("good example matches")

    def test_missing_fixture(self):
        (self.pack / "fixtures" / "demo-security-001.cases").unlink()
        self.assert_fails("missing fixtures/demo-security-001.cases")

    def test_fixture_needs_bad_case_for_rule(self):
        self.write("fixtures/demo-naming-001.cases", CASES["demo-naming-001"].replace(
            "#> expect: demo-naming-001", "#> expect: demo-security-001"))
        self.assert_fails("needs a good case and a bad case expecting demo-naming-001")

    def test_fixture_parser(self):
        cases = vr.parse_cases(CASES["demo-naming-001"] + "#> case bad: edit\n#> path: x.demo\n"
                               "#> tool: Edit\n#> expect: demo-naming-001 demo-security-001\nFoo\n")
        self.assertEqual([c["kind"] for c in cases], ["good", "bad", "bad"])
        self.assertEqual(cases[2]["tool"], "Edit")
        self.assertEqual(cases[2]["expect"], ["demo-naming-001", "demo-security-001"])
        self.assertEqual(cases[0]["body"], "let bar = 1\n")
        for bad in ("#> case bad: x\n#> path: a\nbody\n",
                    "#> case good: x\nbody\n",
                    "#> case good: x\n#> path: ../a\nbody\n",
                    "#> case good: x\n#> path: a\nbody\n#> path: b\n"):
            with self.assertRaises(ValueError, msg=bad):
                vr.parse_cases(bad)

    def test_pack_must_declare_lint(self):
        pack = dict(PACK)
        del pack["lint"]
        self.write_json("pack.json", pack)
        self.assert_fails("declare 'lint'")

    def test_lint_rule_must_be_in_bundled_config(self):
        rule = (REGEX_RULE.replace("demo-naming-001", "demo-style-001").replace("category: naming", "category: style")
                .replace("  method: regex\n", "  method: lint\n  lint_rule_id: no_foo\n")
                .replace("  fragment_safe: true", "  fragment_safe: false"))
        self.write("rules/demo-style-001.md", rule)
        self.write("fixtures/demo-style-001.cases", CASES["demo-naming-001"].replace("naming", "style"))
        self.assert_fails("lint_rule_id 'no_foo' does not appear in demolint.cfg")
        self.write("demolint.cfg", "rules: [no_foo]\n")
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)

    def test_unsupported_schema_keyword_fails(self):
        path = self.root / "plugins/convention-core/schema/rule.schema.json"
        schema = json.loads(path.read_text())
        schema["properties"]["title"]["uniqueItems"] = True
        path.write_text(json.dumps(schema))
        self.assert_fails("unsupported keyword 'uniqueItems'")


if __name__ == "__main__":
    unittest.main()
