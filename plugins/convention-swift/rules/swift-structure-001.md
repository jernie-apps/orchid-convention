---
id: swift-structure-001
stack: swift
category: structure
title: Declare every ViewModel as a class
statement: A type whose name ends in ViewModel must be a class, never a struct or an enum.
rationale: A ViewModel holds mutable state a view observes. As a value type it is copied on assignment, so the view and its owner hold different copies and changes stop reaching the screen, with no error to say why.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])(struct|enum)[[:space:]]+[A-Za-z0-9_]*ViewModel([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "@Observable final class LoginViewModel {"
    - "struct LoginViewModelTests {"
  bad:
    - "struct LoginViewModel {"
    - "enum SettingsViewModel {"
fix: Declare it as a final class with @Observable (see swift-structure-002).
tags: [structure, mvvm, swiftui, state]
---

## Why

The rule checks only the declaration keyword, so it is decidable from one line with no false positives on correctly named types. `LoginViewModelTests` does not match because the name must end in `ViewModel`.

## Examples

```swift
// Good
@Observable
final class LoginViewModel {
    var email = ""
}

// Bad
struct LoginViewModel {
    var email = ""
}
```
