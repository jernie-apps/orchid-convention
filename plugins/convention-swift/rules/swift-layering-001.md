---
id: swift-layering-001
stack: swift
category: layering
title: Keep UI frameworks out of the Domain layer
statement: A file under a Domain/ directory must not import SwiftUI, UIKit, AppKit or WatchKit, including scoped and attributed imports.
rationale: Domain code is the business logic. Once it imports a UI framework it needs a UI runtime to test, cannot be shared with a target that lacks that framework, and starts accepting UI types (Color, UIImage) in its models.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "^[[:space:]]*(@[A-Za-z_]+[[:space:]]+)*import[[:space:]]+((typealias|struct|class|enum|protocol|let|var|func)[[:space:]]+)?(SwiftUI|UIKit|AppKit|WatchKit)([^A-Za-z0-9_]|$)"
  file_glob: "**/Domain/**/*.swift"
  fragment_safe: true
examples:
  good:
    - "import Foundation"
    - "import Observation"
  bad:
    - "import SwiftUI"
    - "@preconcurrency import UIKit"
    - "import struct SwiftUI.Color"
fix: Move the UI-dependent code to the presentation layer, or replace the UI type with a domain value the view maps from.
tags: [layering, imports, architecture]
---

## Why

The Domain layer should compile for any target and test without a simulator. The rule only looks at `import` lines in files below a `Domain/` directory. It does not judge whether a type *belongs* in Domain; that needs whole-repo context and is the scanner's job.

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
