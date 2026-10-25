---
id: swift-security-003
stack: swift
category: security
title: Keep personal data out of logs, analytics and crash reports
statement: Raw personal data (names, email addresses, phone numbers, postal addresses, precise location, government ids, payment details, credentials) must not reach a log, analytics event, breadcrumb or crash-report payload, however it is assembled.
rationale: Personal data in telemetry is a compliance exposure and the most common way it leaks. Whether a value is personal depends on its type and where it came from, which only a whole-file reading can decide, so this rule is judged by the scanner.
state: active
overridable: false
ignorable: false
scope: full-repo
severity: block
introduced: 2026-10-25
detect:
  method: model
  file_glob: "**/*.swift"
  fragment_safe: false
examples:
  good:
    - "analytics.track(.checkoutCompleted, properties: [\"orderId\": order.id.uuidString])"
    - "logger.debug(\"Recipient set for order \\(order.id)\")"
  bad:
    - "print(\"Shipping to \" + order.recipient.name + \", \" + order.recipient.street)"
    - "Crashlytics.crashlytics().setCustomValue(customer.homeAddress, forKey: \"addr\")"
fix: Send a stable non-personal identifier instead, or redact the value before it leaves the process.
tags: [security, logging, pii, analytics]
---

## Why

swift-security-002 catches the obvious one-line case at write time. This rule is the policy itself and covers what a line-based pattern cannot see: concatenation, values passed through helpers, structs logged whole (`print(user)` on a type whose `description` includes the email), analytics properties and crash-report keys.

`method: model` means it is never in `guard.json`. The scan gate judges it on the whole file. `overridable: false`, `scope: full-repo`: a pre-existing leak elsewhere is reported as standing, not grandfathered.

## Examples

```swift
// Good
analytics.track(.checkoutCompleted, properties: ["orderId": order.id.uuidString])

// Bad
print("Shipping to " + order.recipient.name + ", " + order.recipient.street)
Crashlytics.crashlytics().setCustomValue(customer.homeAddress, forKey: "addr")
```
