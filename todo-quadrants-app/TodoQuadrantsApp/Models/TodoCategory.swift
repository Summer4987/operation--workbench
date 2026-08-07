import Foundation

enum TodoCategory: String, CaseIterable, Identifiable, Codable {
    case platform = "平台"
    case directStores = "直营门店"
    case franchise = "加盟业务"
    case supplyChain = "供应链"
    case ai = "AI"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .platform: "rectangle.3.group.fill"
        case .directStores: "storefront.fill"
        case .franchise: "person.2.fill"
        case .supplyChain: "shippingbox.fill"
        case .ai: "sparkles"
        }
    }
}
