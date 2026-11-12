---
id: swift-layering-002
stack: swift
category: layering
title: Keep networking out of SwiftUI views
statement: A file whose name ends in View.swift must not use URLSession or URLRequest; network calls belong in a repository implementation that the feature's Store calls.
rationale: A view that fetches cannot be previewed or snapshot-tested without the network, repeats its request whenever SwiftUI rebuilds it, and hides the call where nobody looks for it. Routing every request through a repository also gives one place for auth, retries and error mapping.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])(URLSession|URLRequest)([^A-Za-z0-9_]|$)"
  file_glob: "**/*View.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - ".task { await store.load() }"
  bad:
    - "let (data, _) = try await URLSession.shared.data(from: url)"
    - "var request = URLRequest(url: endpoint)"
fix: Move the request into a repository implementation (for example RemoteOrderRepository) and call it from the feature's Store.
tags: [layering, swiftui, networking]
---

## Why

The rule is scoped by file name (`*View.swift`), which is the convention SwiftUI views follow, so it is decidable from one line. A view whose file does not end in `View.swift` is not covered by the guard; the scanner can still report it.

## Examples

```swift
// OrderListView.swift, good
.task { await store.load() }

// OrderListView.swift, bad
.task {
    let (data, _) = try? await URLSession.shared.data(from: url)
}
```
