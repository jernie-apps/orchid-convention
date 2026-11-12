---
id: swift-structure-001
stack: swift
category: structure
title: Do not declare ViewModel types
statement: No class, struct, actor or enum may have a name ending in ViewModel; state belongs in a Store per aggregate, a Draft per form, or a <Screen>Model that coordinates several stores.
rationale: A ViewModel per screen is a layer that can hold anything, so form fields, loaded data, rules and network calls all pile up in it. Giving each kind of state its own home (Domain, Draft, Store, View) keeps every type small and makes it obvious where new code goes.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])(class|struct|actor|enum)[[:space:]]+[A-Za-z0-9_]*ViewModel([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "@Observable final class NotesStore {"
    - "struct NoteDraft {"
    - "struct LoginViewModelTests {"
  bad:
    - "@Observable final class LoginViewModel {"
    - "struct LoginViewModel {"
    - "actor SyncViewModel {"
    - "class BaseViewModel<State> {"
fix: Split the type by what it holds. Loaded data of one aggregate goes to an @Observable final class <Aggregate>Store, one form's fields and validation go to a <Form>Draft struct in the view's @State, and business rules go to a pure <Thing>Policy in Domain.
tags: [structure, swiftui, state, four-homes]
---

## Why

This is the `no_view_model` rule of the approved Swift template (ADR 0001, "Four homes for code"), checked before the write instead of after it. The template's source app had one ViewModel that grew to 3240 lines shared by 20 files.

The rule checks only the declared name, so it is decidable from one line. `LoginViewModelTests` does not match because the name must end in `ViewModel`. A `<Screen>Model` that coordinates several stores is allowed; its file starts with a comment saying why, which the guard cannot check.

## Examples

```swift
// Good
@Observable
final class NotesStore {
    private(set) var notes: [Note] = []
}

struct NoteDraft {
    var title = ""
}

// Bad
@Observable
final class NoteListViewModel {
    var notes: [Note] = []
    var draftTitle = ""
}
```
