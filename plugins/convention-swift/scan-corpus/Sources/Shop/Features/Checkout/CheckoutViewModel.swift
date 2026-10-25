import Combine
import Foundation
import OSLog

@MainActor
final class CheckoutViewModel: ObservableObject {
    @Published var total: Decimal = 0
    private let logger = Logger(subsystem: "shop", category: "checkout")

    func confirm(customer: Customer, raw: String) async {
        let url = URL(string: raw)!
        logger.info("Confirming order for customer \(customer.id)")
        print("Receipt for \(customer.email)")
        await submit(to: url)
    }

    private func submit(to url: URL) async {}
}
