---
id: swift-structure-002
stack: swift
category: structure
title: Use @Observable, never ObservableObject
statement: Observable state must use the Observation framework's @Observable macro; ObservableObject, @Published, @StateObject, @ObservedObject and @EnvironmentObject must not appear in any type.
rationale: With @Observable, SwiftUI tracks exactly the properties a view reads, so unrelated changes no longer redraw it, and there is no @Published, objectWillChange or @StateObject/@ObservedObject choice to get wrong. Mixing the two models in one codebase means every reader has to know both. A repo that still supports iOS 16 or earlier, where @Observable is unavailable, should record an override.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])ObservableObject([^A-Za-z0-9_]|$)|@(Published|StateObject|ObservedObject|EnvironmentObject)([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "@MainActor @Observable final class CartStore {"
    - "@State private var store = CartStore()"
    - "@Environment(CartStore.self) private var store"
  bad:
    - "final class CartStore: ObservableObject {"
    - "extension CartStore: ObservableObject {}"
    - "@Published var items: [CartItem] = []"
    - "@StateObject private var store = CartStore()"
    - "@EnvironmentObject var session: Session"
fix: Replace ObservableObject with @Observable, drop @Published, and hold the object with @State (owner), @Environment (shared) or a plain property / @Bindable (child).
tags: [structure, swiftui, observation]
---

## Why

This is the `no_observable_object` rule of the approved Swift template, checked before the write. It applies to every type, whatever its name: a store, a router or a session object is held the same way.

Each of the five names is matched as a whole word, so `MyObservableObjectBridge` and a commented-out line do not match. A third-party type that still requires `ObservableObject` needs a file-level override with its reason.

## Examples

```swift
// Good
@MainActor
@Observable
final class CartStore {
    private(set) var items: [CartItem] = []
}

// Bad
@MainActor
final class CartStore: ObservableObject {
    @Published var items: [CartItem] = []
}
```
