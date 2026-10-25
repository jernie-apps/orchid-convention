---
id: swift-structure-002
stack: swift
category: structure
title: Make ViewModels @Observable, not ObservableObject
statement: A ViewModel class must use the Observation framework's @Observable macro and must not conform to Combine's ObservableObject, in its declaration or in an extension.
rationale: With @Observable, SwiftUI tracks exactly the properties a view reads, so unrelated changes no longer redraw it, and there is no @Published, objectWillChange or @StateObject/@ObservedObject choice to get wrong. Mixing the two models in one codebase means every reader has to know both. A repo that still supports iOS 16 or earlier, where @Observable is unavailable, should record an override.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])(class|extension)[[:space:]]+[A-Za-z0-9_]*ViewModel[^{]*:[^{]*ObservableObject([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "@MainActor @Observable final class CartViewModel {"
    - "final class CartStore: ObservableObject {"
  bad:
    - "final class CartViewModel: ObservableObject {"
    - "@MainActor final class CartViewModel: NSObject, ObservableObject {"
    - "extension CartViewModel: ObservableObject {}"
fix: Replace ObservableObject with @Observable, drop @Published, and hold the model with @State (owner) or a plain property / @Bindable (child).
tags: [structure, mvvm, swiftui, observation]
---

## Why

The rule is scoped to types named `*ViewModel`; other `ObservableObject` types (a legacy store, a third-party bridge) are out of its reach on purpose. The declaration must be on one line for the guard to see it; a conformance split across lines is left to the scanner.

## Examples

```swift
// Good
@MainActor
@Observable
final class CartViewModel {
    var items: [CartItem] = []
}

// Bad
@MainActor
final class CartViewModel: ObservableObject {
    @Published var items: [CartItem] = []
}
```
