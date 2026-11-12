import SwiftUI

struct PromoBannerView: View {
    @State private var title = ""

    var body: some View {
        Text(title)
            .onAppear {
                Task.detached {
                    let (data, _) = try await URLSession.shared.data(from: PromoBannerView.endpoint)
                    title = String(decoding: data, as: UTF8.self)
                }
            }
    }

    static let endpoint = URL(filePath: "/promo")
}
