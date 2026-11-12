---
id: swift-structure-003
stack: swift
category: structure
title: Name each file after what it holds; no unrelated types
statement: A Swift file is named after its primary top-level type, or after the one concept all its types share; other top-level types may share the file only when they support the primary one (its typed ID, input, error, change or cursor values, schema versions, private subviews and helpers).
rationale: Navigation by name (Open Quickly, file search, code review links) only works when the file is named after what it holds. Small values that only make sense next to their owner are easier to read beside it, but an unrelated type hidden in someone else's file is found by nobody.
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
    - "// Note.swift: struct NoteID {}, struct Note {} and struct NoteInput {}"
    - "// NoteRepository.swift: enum NoteRepositoryError {}, enum NoteChange {} and protocol NoteRepository {}"
    - "// NoteListView.swift: struct NoteListView {} plus private struct NoteRow {}"
    - "// OrderService+Retry.swift: extension OrderService {}"
  bad:
    - "// OrderService.swift: final class OrderService {} plus struct OrderCache {}"
    - "// Helpers.swift: struct DateFormatting {}"
fix: Move the unrelated type into its own file, or rename the file after the type or concept it holds.
tags: [structure, navigation]
---

## Why

The approved Swift template keeps an aggregate's small values beside their owner: `Note.swift` holds `NoteID`, `Note` and `NoteInput`; `NoteRepository.swift` holds the protocol with its error and change types; `Schema.swift` holds the schema versions and their migration plan; a view file holds its private subview structs. The rule allows that and still rejects a file that collects unrelated types or is named for nothing in it.

A supporting type is one a reader would look for under the primary type's name. A type with its own collaborators, behaviour or callers elsewhere (a cache next to a service, a second view model of data) is not one and gets its own file.

Deciding this needs the whole file and its name: an edit fragment shows neither, so the rule is scanner-only and never in `guard.json`. `Type+Feature.swift` files holding extensions of `Type` satisfy it.

## Examples

```swift
// Note.swift, good
struct NoteID: Hashable, Sendable { }
struct Note: Identifiable { }
struct NoteInput { }

// OrderService.swift, bad
final class OrderService { }
struct OrderCache { }
```
