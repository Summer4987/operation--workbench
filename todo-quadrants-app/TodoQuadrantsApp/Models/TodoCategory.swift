import Foundation

enum TodoCategory: String, CaseIterable, Identifiable, Codable {
    case platform = "平台"
    case directStores = "直营门店"
    case franchise = "加盟业务"
    case supplyChain = "供应链"
    case ai = "AI"

    var id: String { rawValue }
}
