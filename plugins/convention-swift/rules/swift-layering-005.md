---
id: swift-layering-005
stack: swift
category: layering
title: Features do not reference each other
statement: Code under Features/<A>/ must not use a type declared under Features/<B>/; a type two features need moves to Domain, or to Core when it is UI.
rationale: A feature that reaches into another cannot be changed, moved or deleted on its own, and the two soon need each other in both directions. Shared types in Domain or Core keep every feature a leaf that depends only on the layers below it.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-11-13
detect:
  method: model
  file_glob: "**/Features/**/*.swift"
  fragment_safe: false
examples:
  good:
    - "// Features/Notes/NoteListView.swift uses NotesStore (same feature), Note (Domain) and LoadPhaseView (Core)"
    - "// App/RootView.swift composes NotesTab and SettingsTab: the app target may see every feature"
  bad:
    - "// Features/Checkout/CheckoutStore.swift reads PromoBannerView.endpoint from Features/Banner"
    - "// Features/Notes/NoteListView.swift pushes SettingsRoute.profile from Features/Settings"
fix: Move the shared type to Domain (or Core for UI). For navigation between features, route through the app target or a route type declared in Core.
tags: [layering, features, modularity]
---

## Why

The approved Swift template checks this in `scripts/ci.sh` by matching type names, and calls it partly enforced. Knowing where a type is declared needs the repository, not one line, so the pack rule is scanner-only and never in `guard.json`.

The feature is the first directory under `Features/`. Types from Domain, Data's public repositories, Core and the feature's own folder are fine. The app target (`App/`) is outside `Features/` and composes them all.

## Examples

```swift
// Features/Notes/NoteList/NoteListView.swift, good
@Environment(NotesStore.self) private var store

// Features/Notes/NoteList/NoteListView.swift, bad
@Environment(SettingsStore.self) private var settings   // declared in Features/Settings
```
