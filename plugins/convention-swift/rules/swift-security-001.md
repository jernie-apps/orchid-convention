---
id: swift-security-001
stack: swift
category: security
title: Never hardcode a secret in source
statement: A variable or constant whose name ends in a secret-like word (apiKey, secret, token, password, passwd) must not be assigned a non-empty string literal.
rationale: A literal secret is committed to history for good and shipped inside the binary, where strings are trivially extracted. No repo may vote this rule down, and the guard never offers a human prompt to wave one through.
state: active
overridable: false
ignorable: false
scope: full-repo
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "[A-Za-z0-9_]*(api_?key|secret|token|password|passwd)[[:space:]]*(:[[:space:]]*String[[:space:]]*)?=[[:space:]]*\"[^\"]+\""
  flags: "i"
  file_glob: "**/*.swift"
  exclude_glob: "**/{Mock,Mocks}/**"
  exclude_pattern: "^[[:space:]]*//|(^|[^A-Za-z0-9_])case[[:space:]]"
  fragment_safe: true
examples:
  good:
    - "let apiKey = Bundle.main.object(forInfoDictionaryKey: \"API_KEY\") as? String"
    - "let token = try keychain.read(.authToken)"
    - "if token == \"\" { return }"
    - "case password = \"^.{8,}$\""
  bad:
    - "let apiKey = \"sk_live_51H8xQ\""
    - "static let authToken: String = \"eyJhbGciOi\""
    - "private let clientSecret = \"s3cr3t\""
fix: Read the value from the Keychain, a build-time configuration that is not committed, or a secrets service. Rotate any secret that was ever committed.
tags: [security, secrets]
---

## Why

`overridable: false` and `scope: full-repo`: the rule is not grandfathered, cannot be overridden in `.orchid/conventions/swift.md`, and is never escalated by the guard's two-strike prompt.

Two exclusions keep the false-positive rate down, because a non-overridable rule that cries wolf teaches people to ignore the blocking tier:

- `**/Mock/**` and `**/Mocks/**`: a fake credential in a test double is the point of the file.
- Comment lines and `case` raw values: `case password = "^.{8,}$"` is a validation pattern, not a password.

A commented-out credential is still a committed credential. The exclusion means a write-time guard cannot usefully block a comment; the remedy for a leaked secret is rotation.

## Examples

```swift
// Good
let apiKey = Bundle.main.object(forInfoDictionaryKey: "API_KEY") as? String

// Bad
let apiKey = "sk_live_51H8xQ"
```
