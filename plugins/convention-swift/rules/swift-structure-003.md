---
id: swift-structure-003
stack: swift
category: structure
title: One primary type per file, named like the file
statement: Each Swift file declares one primary top-level type whose name matches the file name; extensions of that type and private or fileprivate helpers it alone uses may share the file.
rationale: Navigation by name (Open Quickly, file search, code review links) only works when the file is named after what it holds, and one type per file keeps each diff about one thing.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: model
  file_glob: "**/*.swift"
  fragment_safe: false
examples:
  good:
    - "// OrderService.swift: final class OrderService {} plus private struct Endpoint {}"
    - "// OrderService+Retry.swift: extension OrderService {}"
  bad:
    - "// OrderService.swift: final class OrderService {} plus struct OrderCache {}"
    - "// Helpers.swift: struct DateFormatting {}"
fix: Move the extra type into its own file, or rename the file after the type it holds.
tags: [structure, navigation]
---

## Why

Deciding this needs the whole file and its name: an edit fragment shows neither, so the rule is scanner-only and never in `guard.json`. `Type+Feature.swift` files holding extensions of `Type` satisfy it.

## Examples

```swift
// OrderService.swift, good
final class OrderService { }
private struct Endpoint { }

// OrderService.swift, bad
final class OrderService { }
struct OrderCache { }
```
