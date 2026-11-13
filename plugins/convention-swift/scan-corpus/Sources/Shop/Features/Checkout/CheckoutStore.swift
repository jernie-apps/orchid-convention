import Foundation
import Observation

@MainActor
@Observable
final class CheckoutStore {
    private(set) var orders: [Order] = []
    private(set) var coupons: [Coupon] = []
    private let orderRepository: any OrderRepository
    private let couponRepository: any CouponRepository

    init(orderRepository: any OrderRepository, couponRepository: any CouponRepository) {
        self.orderRepository = orderRepository
        self.couponRepository = couponRepository
    }

    func promoURL() -> URL {
        PromoBannerView.endpoint
    }
}
