---
id: swift-style-002
stack: swift
category: style
title: Log through the Log wrapper, never print or os directly
statement: Code outside a Logging/ directory must not call print, debugPrint, NSLog or os_log, create an os Logger, or import os or OSLog; it logs through the project Log wrapper.
rationale: print reaches the console of every build with no level, category or redaction, and a Logger created ad hoc picks its own subsystem and privacy rules. One wrapper gives every message a category and one place that decides what is public and what is redacted.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-12
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_.])(print|debugPrint|NSLog|os_log)[[:space:]]*\\(|(^|[^A-Za-z0-9_])Logger[[:space:]]*\\(|^[[:space:]]*import[[:space:]]+(os|OSLog)([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_glob: "**/Logging/**"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "log.info(\"Saved note\")"
    - "log.error(\"Save failed\", sensitive: error.localizedDescription)"
    - "blueprint(for: plan)"
  bad:
    - "print(\"Saved note\")"
    - "debugPrint(note)"
    - "NSLog(\"Saved %@\", note.title)"
    - "private let logger = Logger(subsystem: \"app\", category: \"notes\")"
    - "import OSLog"
fix: Use the Log wrapper (Core/Logging/Log.swift in the template) and pass anything personal in its sensitive argument.
tags: [style, logging, privacy]
---

## Why

This covers the `no_print` and `no_direct_logging` rules of the approved Swift template, checked before the write. Only the files under a `Logging/` directory (the template's `Core/Logging/Log.swift`) may import `OSLog` and create a `Logger`.

`Log` takes a public message and an optional `sensitive:` string that is redacted outside the debugger, so user content never has to be interpolated into the message. Interpolating a personal-data field into any log call stays blocked by `swift-security-002`, which no repo can override.

## Examples

```swift
// Good
log.info("Saved note", sensitive: note.title)

// Bad
print("Saved note \(note.title)")
```
