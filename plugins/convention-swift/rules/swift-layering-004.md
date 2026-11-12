---
id: swift-layering-004
stack: swift
category: layering
title: Reference .shared only in the composition root
statement: A .shared singleton must not be referenced outside AppDependencies.swift; dependencies are created there and reach views through the environment.
rationale: A singleton reached from anywhere is a hidden dependency. The type cannot be tested or previewed with a substitute, and nothing in its signature says what it needs. Creating every long-lived dependency in one file makes the wiring visible and replaceable.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-12
detect:
  method: regex
  pattern: "\\.shared([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_glob: "**/AppDependencies.swift"
  exclude_pattern: "^[[:space:]]*//|swiftlint:disable:this[[:space:]]+no_shared_singleton"
  fragment_safe: true
examples:
  good:
    - "@Environment(NotesStore.self) private var store"
    - "init(session: URLSession) { self.session = session }"
    - "UIApplication.shared.open(url) // swiftlint:disable:this no_shared_singleton - system URL handler"
  bad:
    - "let (data, _) = try await URLSession.shared.data(from: url)"
    - "AnalyticsClient.shared.track(event)"
    - "let center = NotificationCenter.default; let app = UIApplication.shared"
fix: Create the dependency in AppDependencies.swift and pass it in through an initializer or .environment. A justified use of an Apple singleton carries a same-line // swiftlint:disable:this no_shared_singleton comment with the reason.
tags: [layering, dependencies, composition-root]
---

## Why

This is the `no_shared_singleton` rule of the approved Swift template (ADR 0007), checked before the write. `App/AppDependencies.swift` is the composition root: the only file that creates long-lived dependencies.

The match is on the text `.shared`, so Apple singletons (`UIApplication.shared`, `URLSession.shared`) are flagged too. That is intended: most of them should be injected. A justified exception puts `// swiftlint:disable:this no_shared_singleton` and its reason on the same line, which satisfies both this guard and the template's SwiftLint rule. The guard reads one line at a time, so the `disable:next` form on the line above is not seen by it.

## Examples

```swift
// AppDependencies.swift, good
let session = URLSession.shared

// OrderService.swift, good
init(session: URLSession) { self.session = session }

// OrderService.swift, bad
let (data, _) = try await URLSession.shared.data(from: url)
```
