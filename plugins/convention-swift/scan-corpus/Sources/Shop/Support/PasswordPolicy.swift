import Foundation
import OSLog

// Traps: none of these lines is a violation.
enum PasswordPolicy: String {
    case password = "^.{8,}$"
    case pin = "^[0-9]{6}$"
}

// let apiKey = "sk_test_example_only"

struct PolicyLogger {
    let logger = Logger(subsystem: "shop", category: "policy")

    func checked(_ user: User) {
        logger.info("Policy checked for \(user.email, privacy: .private)")
        logger.debug("Email verified: \(user.isEmailVerified)")
    }
}
