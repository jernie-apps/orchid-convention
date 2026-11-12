# convention-swift

Swift 6 and SwiftUI rule pack for Orchid Convention. It is data only: [`convention-core`](../convention-core/README.md) reads `pack.json`, `guard.json` and `rules/`, so install core alongside it.

## Rules

| Id | Rule | Detected by | Repo can override |
| --- | --- | --- | --- |
| [`swift-naming-001`](rules/swift-naming-001.md) | Protocols take no I- prefix or -Protocol suffix | guard | yes |
| [`swift-layering-001`](rules/swift-layering-001.md) | Non-test files under `Domain/` import Foundation only | guard | yes |
| [`swift-security-001`](rules/swift-security-001.md) | No hardcoded secret literals | guard | **no** |
| [`swift-security-002`](rules/swift-security-002.md) | No personal-data field interpolated into a log call | guard | **no** |
| [`swift-security-003`](rules/swift-security-003.md) | No personal data in logs, analytics or crash reports | scanner | **no** |
| [`swift-structure-001`](rules/swift-structure-001.md) | No `*ViewModel` types: use a Store, a Draft or a `<Screen>Model` | guard | yes |
| [`swift-structure-002`](rules/swift-structure-002.md) | `@Observable` only: no `ObservableObject`, `@Published`, `@StateObject`, `@ObservedObject`, `@EnvironmentObject` | guard | yes |
| [`swift-structure-003`](rules/swift-structure-003.md) | A file is named after what it holds; extra types only if they support the primary one | scanner | yes |
| [`swift-layering-002`](rules/swift-layering-002.md) | `*View.swift` files never use `URLSession` or `URLRequest` | guard | yes |
| [`swift-concurrency-001`](rules/swift-concurrency-001.md) | No `Task.detached` or `onAppear` Task in a view; load in `.task { }` (warn) | guard | yes |
| [`swift-concurrency-002`](rules/swift-concurrency-002.md) | `@unchecked Sendable` carries a same-line `// SAFETY:` justification | guard | yes |
| [`swift-style-001`](rules/swift-style-001.md) | No force unwrapping (SwiftLint `force_unwrapping`, warn) | lint | yes |

"guard" rules are fragment-safe regexes, mirrored in `guard.json` and checked before every write. "lint" rules run through SwiftLint after the write. "scanner" rules need the whole file and are judged by the scan gate, which is not built yet; until then they are documented and fixture-covered but not enforced.

## Scan corpus

[`scan-corpus/`](scan-corpus) is the answer key for scanner runs: five files with ten required planted violations (seven found by the regex sweep, three only by reading) and trap lines that must not be reported (an enum raw value, a commented-out key, a redacted email). CI checks the sweep half; the judged half is measured by hand with `score_findings.py` (see the core README).

## Lint

`pack.json` declares `swiftlint lint --quiet [--config <file>] <file>`. The repo's own `.swiftlint.yml`, found upward from the written file, wins over the bundled [`.swiftlint.yml`](.swiftlint.yml). Without `swiftlint` on `PATH`, the session is told once that Swift lint did not run.

## Overrides

A repo switches off an overridable rule in `.orchid/conventions/swift.md`:

```markdown
## swift-structure-002
override: global
reason: The app still supports iOS 16, where @Observable is unavailable.
```

The security rules ignore such a block, and the guard says so when it fires.

## Adding or changing a rule

1. Add `rules/swift-<category>-<NNN>.md` with a new id. Never reuse or delete an id; retire it with `state: removed`.
2. If it is a fragment-safe regex, mirror it into `guard.json` with a message. Patterns are portable POSIX ERE matched per line: no `\s`, `\w`, `\d`, `\b` or `(?`.
3. Add `fixtures/<id>.cases` with at least one good case and one bad case that expects it. Bad cases list every rule they break.
4. Run `python3 plugins/convention-core/scripts/validate_rules.py` and `python3 plugins/convention-core/scripts/run_fixtures.py plugins/convention-swift`.
