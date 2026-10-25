import Foundation

final class ReceiptMailer: @unchecked Sendable {
    private var queue: [Receipt] = []

    func send(_ receipt: Receipt) {
        queue.append(receipt)
        print("Mailing receipt to " + receipt.customer.name + " at " + receipt.customer.street)
    }
}

struct ReceiptTemplate {
    let subject: String
    let body: String
}
