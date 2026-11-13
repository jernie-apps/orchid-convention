---
id: swift-structure-004
stack: swift
category: structure
title: One aggregate per Store
statement: A Store holds the loaded data of exactly one aggregate and talks to that aggregate's repository only; it holds no form fields, sheet or alert flags, and no second aggregate's data.
rationale: A store that may hold anything becomes the ViewModel it replaced. The template this rule comes from was extracted from an app whose largest state object reached 3240 lines and 152 properties, shared by 20 files. One aggregate per store keeps each store small and gives every piece of loaded data one owner.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-13
detect:
  method: model
  file_glob: "**/*Store.swift"
  fragment_safe: false
examples:
  good:
    - "// NotesStore.swift: notes, phase and one NoteRepository"
    - "// DashboardModel.swift: a screen model that reads NotesStore and TagsStore, with a comment saying why"
  bad:
    - "// NotesStore.swift: notes and tags, with a NoteRepository and a TagRepository"
    - "// NotesStore.swift: notes plus draftTitle and isShowingDeleteAlert"
fix: Give the second aggregate its own Store. Move form fields to a Draft struct in the view's @State and presentation flags to the view. A screen that needs several stores reads them all, or uses a <Screen>Model that coordinates them.
tags: [structure, state, four-homes]
---

## Why

This is the Store row of the approved Swift template's four homes (ADR 0001). The template lists it as not mechanically enforced: no regex can tell that `tags` is a second aggregate and `phase` is not, so the rule is scanner-only and never in `guard.json`.

Signs of a second aggregate: a second repository, a second collection of an unrelated entity type, or load and mutate functions for two different things. Derived values of the same aggregate (a filtered list, a load phase, a paging cursor) are fine.

## Examples

```swift
// NotesStore.swift, good
@Observable
final class NotesStore {
    private(set) var notes: [Note] = []
    private(set) var phase: LoadPhase = .idle
    private let repository: any NoteRepository
}

// NotesStore.swift, bad
@Observable
final class NotesStore {
    private(set) var notes: [Note] = []
    private(set) var tags: [Tag] = []
    var draftTitle = ""
    var isShowingDeleteAlert = false
}
```
