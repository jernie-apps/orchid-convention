---
id: swift-concurrency-001
stack: swift
category: concurrency
title: Load in .task, not in a detached or onAppear Task
statement: A file whose name ends in View.swift should not call Task.detached or start a Task from onAppear; load in the .task modifier, and keep a plain Task for user actions such as a button tap.
rationale: A Task started in onAppear outlives the view. It keeps running after the screen is dismissed and is never cancelled, while the .task modifier ties the work to the view's lifetime. Task.detached also drops the main-actor isolation and task-local values a view relies on; work that must leave the main actor belongs in a @concurrent function the store calls.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: warn
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_.])Task\\.detached([^A-Za-z0-9_]|$)|\\.onAppear[^A-Za-z0-9_].*[^A-Za-z0-9_.]Task[[:space:]]*(\\([^)]*\\))?[[:space:]]*\\{"
  file_glob: "**/*View.swift"
  exclude_pattern: "^[[:space:]]*//|=[[:space:]]*Task"
  fragment_safe: true
examples:
  good:
    - ".task { await store.load() }"
    - "Button(.notesSave) { Task { await save() } }"
    - "refreshTask = Task.detached { await store.refresh() }"
  bad:
    - "Task.detached(priority: .background) {"
    - ".onAppear { Task { await store.load() } }"
fix: Use .task { } (or .task(id:) to restart on change) for loading and streams. For work that must leave the main actor, mark the callee @concurrent instead of detaching.
tags: [concurrency, swiftui, lifetime]
---

## Why

The approved Swift template consumes live data in `.task` and starts a plain `Task { await save() }` from button actions: an action is short, user-initiated and has no modifier of its own, so the guard leaves it alone. Assigning the Task (`loadTask = Task { ... }`) counts as owning it and is not flagged either.

Severity is `warn`. The guard sees one line at a time, so it catches `Task.detached` anywhere in a view file and a Task on the same line as `.onAppear`; a Task on the line after `.onAppear {` is left to the scanner.

## Examples

```swift
// Good
.task { await store.load() }

Button(.notesSave) {
    Task { await save() }
}

// Flagged
.onAppear { Task { await store.load() } }

Task.detached { await store.prefetch() }
```
