---
id: swift-naming-001
stack: swift
category: naming
title: Name protocols for what they describe, without I- or -Protocol
statement: A protocol name must not use an interface prefix (IUserStore) or a Protocol suffix (UserStoreProtocol).
rationale: Swift protocols describe a role or a capability (Sequence, Equatable, UserStore) and value types conform to them constantly. A decorated name imports a convention from Java and C#, adds nothing a Swift reader needs, and makes the concrete type harder to name.
state: active
overridable: true
ignorable: true
scope: changed-files
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(^|[^A-Za-z0-9_])protocol[[:space:]]+(I[A-Z][a-z][A-Za-z0-9_]*|[A-Za-z0-9_]+Protocol)([^A-Za-z0-9_]|$)"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//"
  fragment_safe: true
examples:
  good:
    - "protocol UserStore { func user(id: User.ID) async throws -> User }"
    - "protocol IPAddressConvertible { var ipAddress: String { get } }"
  bad:
    - "protocol IUserStore { func user(id: User.ID) async throws -> User }"
    - "public protocol UserStoreProtocol: Sendable { }"
fix: Drop the I- prefix or -Protocol suffix and name the protocol for its role; name the concrete type for how it does it (RemoteUserStore).
tags: [naming, protocols]
---

## Why

The Swift API Design Guidelines name protocols as nouns for what something *is* (`Collection`) or with `-able`/`-ible` for what it *can do* (`Equatable`). The concrete type then carries the detail: `UserStore` is the protocol, `RemoteUserStore` and `InMemoryUserStore` are implementations.

The pattern needs an uppercase letter followed by a lowercase one after the `I`, so acronyms such as `IPAddressConvertible` are not flagged.

## Examples

```swift
// Good
protocol UserStore {
    func user(id: User.ID) async throws -> User
}

// Bad
protocol IUserStore { }
protocol UserStoreProtocol { }
```
