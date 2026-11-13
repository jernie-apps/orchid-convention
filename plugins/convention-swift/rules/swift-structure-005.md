---
id: swift-structure-005
stack: swift
category: structure
title: A Draft holds one form's fields, nothing loaded
statement: A Draft is a struct with the editable fields and validation of one form; it holds no loaded entities or collections, no repository or store, and does no async work.
rationale: A draft is a value owned by one view, so form state cannot pile up in a shared object and is discarded with the screen. Once it holds loaded data or calls a repository it needs a lifetime and an owner, which is what a Store is for.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-13
detect:
  method: model
  file_glob: "**/*Draft.swift"
  fragment_safe: false
examples:
  good:
    - "// NoteDraft.swift: struct with title, body, init(note:) and a validate() that calls NotePolicy"
    - "// NoteDraft.swift: var input: NoteInput built from the fields"
  bad:
    - "// NoteDraft.swift: var allNotes: [Note] and func save() async that calls a repository"
    - "// NoteDraft.swift: @Observable final class NoteDraft"
fix: Keep only the form's fields and validation in the Draft. Load and save through the Store, and pass the Draft's input value to it.
tags: [structure, state, forms, four-homes]
---

## Why

This is the Draft row of the approved Swift template's four homes (ADR 0001), listed there as not mechanically enforced. Telling an editable field from loaded data needs the whole type, so the rule is scanner-only and never in `guard.json`.

A draft may be initialised from an entity (`init(note:)`) and may produce an input value for the repository (`NoteInput`). It may call a pure Domain policy to validate. It may not keep the entity list, hold a store or repository, or be a class.

## Examples

```swift
// NoteDraft.swift, good
struct NoteDraft {
    var title = ""
    var body = ""

    func validate() throws(NoteValidationError) { try NotePolicy.validate(title: title) }
}

// NoteDraft.swift, bad
struct NoteDraft {
    var title = ""
    var allNotes: [Note] = []
    let repository: any NoteRepository

    func save() async throws { try await repository.save(input) }
}
```
