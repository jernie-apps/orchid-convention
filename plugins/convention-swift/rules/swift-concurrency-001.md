---
id: swift-concurrency-001
stack: swift
category: concurrency
title: Do not start unowned Tasks in a view
statement: A file whose name ends in View.swift should not start a Task or Task.detached that nothing stores; use the .task modifier, or keep the Task and cancel it.
rationale: An unowned Task outlives the view that started it. It keeps running after the screen is dismissed, can write state into a view that is gone, and is never cancelled. The .task modifier ties the work to the view's lifetime and cancels it automatically.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: warn
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_.])Task(\\.detached)?[[:space:]]*(\\([^)]*\\))?[[:space:]]*\\{"
  file_glob: "**/*View.swift"
  exclude_pattern: "^[[:space:]]*//|=[[:space:]]*Task"
  fragment_safe: true
examples:
  good:
    - ".task { await viewModel.load() }"
    - "loadTask = Task { await viewModel.load() }"
  bad:
    - "Button(\"Reload\") { Task { await viewModel.load() } }"
    - "Task.detached(priority: .background) {"
fix: Use .task { } (or .task(id:) to restart on change), or store the Task in state and cancel it in onDisappear.
tags: [concurrency, swiftui, lifetime]
---

## Why

Severity is `warn`: a short `Task { }` inside a button action is common and sometimes acceptable, so the guard flags it as context without blocking. Assigning the Task (`loadTask = Task { ... }`) counts as owning it and is not flagged.

## Examples

```swift
// Good
.task { await viewModel.load() }

// Flagged
Button("Reload") {
    Task { await viewModel.load() }
}
```
