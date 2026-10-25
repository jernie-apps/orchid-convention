---
id: swift-concurrency-002
stack: swift
category: concurrency
title: Justify every @unchecked Sendable on the same line
statement: "A conformance to @unchecked Sendable must carry a same-line comment, // SAFETY: <how the mutable state is protected>."
rationale: "@unchecked Sendable switches off Swift 6's data-race checking for the type. That is sometimes right (state guarded by a lock the compiler cannot see), but without a written reason nobody can tell a deliberate exception from a silenced warning, and the next edit can break the invariant unnoticed."
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "@unchecked[[:space:]]+Sendable"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//|//[[:space:]]*SAFETY:[[:space:]]*[^[:space:]]"
  fragment_safe: true
examples:
  good:
    - "final class ImageCache: @unchecked Sendable { // SAFETY: every access goes through lock"
    - "actor ImageCache {"
  bad:
    - "final class ImageCache: @unchecked Sendable {"
    - "extension Legacy: @unchecked Sendable {} // TODO"
fix: "Prefer an actor, a Mutex or an immutable value type; if the exception is real, add // SAFETY: <mechanism> on the same line."
tags: [concurrency, swift6, sendable]
---

## Why

The justification must be on the same line because the guard reads one line at a time; a comment on the line above is not seen and the write is denied.

## Examples

```swift
// Good
final class ImageCache: @unchecked Sendable { // SAFETY: every access goes through `lock`
    private let lock = NSLock()
    private var storage: [URL: Image] = [:]
}

// Bad
final class ImageCache: @unchecked Sendable {
    private var storage: [URL: Image] = [:]
}
```
