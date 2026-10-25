import Foundation
import SwiftUI

struct PriceRule: Equatable, Sendable {
    let minimumQuantity: Int
    let discount: Decimal
}
