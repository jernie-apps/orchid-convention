---
id: swift-style-001
stack: swift
category: style
title: Avoid force unwrapping
statement: Production Swift code should not force unwrap optionals with the postfix ! operator; bind, default or throw instead.
rationale: A force unwrap turns an unexpected nil into a crash with no context. Binding or defaulting makes the nil case visible in the code, where review can judge it.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: warn
introduced: 2026-10-25
detect:
  method: lint
  lint_rule_id: force_unwrapping
  file_glob: "**/*.swift"
  fragment_safe: false
examples:
  good:
    - "guard let url = URL(string: raw) else { throw ConfigError.badURL(raw) }"
  bad:
    - "let url = URL(string: raw)!"
fix: Use guard let, if let, ?? with a sensible default, or throw a descriptive error.
tags: [style, safety, swiftlint]
---

## Why

SwiftLint's `force_unwrapping` rule already parses Swift correctly (it knows `!=` and implicitly unwrapped declarations are different), so this rule delegates to it through the pack's lint layer rather than a regex. It is enabled in the bundled `.swiftlint.yml`; a repo with its own config must opt in to `force_unwrapping` for the rule to run.

## Examples

```swift
// Good
guard let url = URL(string: raw) else { throw ConfigError.badURL(raw) }

// Bad
let url = URL(string: raw)!
```
