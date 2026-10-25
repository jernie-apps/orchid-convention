---
id: swift-security-002
stack: swift
category: security
title: Never interpolate a personal-data field into a log call
statement: A print, NSLog, os_log or Logger call must not interpolate a field named for personal data (email, phone number, full, first or last name, date of birth, national or social security id, passport or card number) unless os.Logger redacts it with privacy .private or .sensitive.
rationale: Logs reach crash reporters, log aggregators and support tools with far wider access than the data itself, and personal data in them is a compliance exposure. This is the mechanical half of the PII-in-logs policy, decidable from one line; swift-security-003 covers the cases that need judgement.
state: active
overridable: false
ignorable: false
scope: full-repo
severity: block
introduced: 2026-10-25
detect:
  method: regex
  pattern: "(print|debugPrint|NSLog|os_log|\\.(trace|debug|info|notice|log|warning|error|critical|fault))[[:space:]]*\\(.*\\\\\\([^)]*(email|emailAddress|phoneNumber|mobileNumber|fullName|firstName|lastName|dateOfBirth|birthDate|ssn|socialSecurityNumber|nationalId|passportNumber|creditCardNumber|cardNumber)[[:space:]]*[,)]"
  flags: "i"
  file_glob: "**/*.swift"
  exclude_pattern: "^[[:space:]]*//|privacy:[[:space:]]*\\.(private|sensitive)"
  fragment_safe: true
examples:
  good:
    - "logger.info(\"Signed in user \\(user.id)\")"
    - "logger.info(\"Signed in \\(user.email, privacy: .private)\")"
    - "print(\"Verified: \\(user.isEmailVerified)\")"
  bad:
    - "logger.info(\"Signed in \\(user.email)\")"
    - "print(\"Calling \\(contact.phoneNumber)\")"
    - "logger.error(\"Lookup failed for \\(profile.fullName, privacy: .public)\")"
fix: Log a stable non-personal identifier (user.id), or redact the field with os.Logger's privacy .private.
tags: [security, logging, pii]
---

## Why

`overridable: false` and `scope: full-repo`, like swift-security-001.

The field must be the last component of the interpolation, so `\(user.isEmailVerified)` passes while `\(user.email)` and `\(user.email, privacy: .public)` do not. `os.Logger` interpolation marked `privacy: .private` or `.sensitive` is redacted in collected logs and passes.

String concatenation, values passed through a helper, or PII under an unrevealing name are not decidable from one line. The scanner judges those under swift-security-003.

## Examples

```swift
// Good
logger.info("Signed in user \(user.id)")
logger.info("Signed in \(user.email, privacy: .private)")

// Bad
logger.info("Signed in \(user.email)")
print("Calling \(contact.phoneNumber)")
```
