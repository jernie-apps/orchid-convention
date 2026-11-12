---
id: swift-layering-001
stack: swift
category: layering
title: Domain imports Foundation only
statement: A non-test file under a Domain/ directory may import Foundation and nothing else, including scoped and attributed imports.
rationale: Domain code is the business logic. Once it imports a UI, persistence or reactive framework it needs that runtime to test, cannot be reused behind another backend, and starts accepting framework types (Color, a SwiftData model, a publisher) in its entities and repository protocols.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+[A-Za-z_]"
  file_glob: "**/Domain/**/*.swift"
  exclude_glob: "**/Tests/**"
  exclude_pattern: "^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+((typealias|struct|class|enum|protocol|let|var|func)[[:space:]]+)?Foundation([^A-Za-z0-9_]|$)"
  fragment_safe: true
examples:
  good:
    - "import Foundation"
    - "import struct Foundation.UUID"
  bad:
    - "import SwiftUI"
    - "import SwiftData"
    - "import Observation"
    - "@preconcurrency import UIKit"
    - "import struct SwiftUI.Color"
fix: Move the UI-dependent code to a view, persistence and networking to the Data layer, and observable state to a Store; keep Domain to values, policies and repository protocols.
tags: [layering, imports, architecture]
---

## Why

This is the `domain_imports_foundation_only` rule of the approved Swift template (ADR 0002), checked before the write. The template's Domain package makes SwiftData, SwiftUI, UIKit and CoreData fail to compile; Combine and Observation cannot be blocked that way, so the import line is the only place to stop them.

The rule looks at `import` lines in files below a `Domain/` directory and skips anything under a `Tests/` directory, where `import Testing` and `@testable import Domain` are expected. It does not judge whether a type *belongs* in Domain; that needs whole-repo context and is the scanner's job.

## Examples

```swift
// Domain/Order/OrderTotal.swift, good
import Foundation

struct OrderTotal: Equatable, Sendable {
    let amount: Decimal
}

// Domain/Order/OrderTotal.swift, bad
import SwiftUI

struct OrderTotal {
    let tint: Color
}
```
