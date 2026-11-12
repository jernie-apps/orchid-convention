---
id: swift-layering-003
stack: swift
category: layering
title: Views call stores, never repositories
statement: A file whose name ends in View.swift must not mention a repository, in code or in a comment; the view calls its feature Store and the Store calls the repository.
rationale: A view that holds a repository does its own loading, error handling and caching, so the same logic is repeated on every screen and cannot be tested without the UI. Going through the Store keeps one owner for an aggregate and lets every screen of a feature observe the same data.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-12
detect:
  method: regex
  pattern: "[Rr]epository"
  file_glob: "**/*View.swift"
  fragment_safe: true
examples:
  good:
    - "@Environment(NotesStore.self) private var store"
    - ".task { await store.load() }"
  bad:
    - "let repository: any NoteRepository"
    - "@Environment(\\.noteRepository) private var notes"
    - "let notes = try await SwiftDataNoteRepository(container).all()"
fix: Move the call into the feature's Store and read the result from the Store in the view.
tags: [layering, swiftui, four-homes]
---

## Why

This is the `no_repository_in_view` rule of the approved Swift template (ADR 0001), checked before the write. Like the template's rule it is a text match on the word, comments included, so a view cannot keep a repository under a commented-out line either.

The guard scopes by file name (`*View.swift`). The template's SwiftLint rule also covers a `View` conformance declared in a file with another name; that case is caught after the write by the lint layer.

## Examples

```swift
// NoteListView.swift, good
@Environment(NotesStore.self) private var store

// NoteListView.swift, bad
let repository: any NoteRepository
```
