import Foundation

enum PriorityQuadrant: String, CaseIterable, Identifiable, Codable {
    case importantUrgent = "重要且紧急"
    case importantNotUrgent = "重要不紧急"
    case urgentNotImportant = "紧急不重要"
    case notUrgentNotImportant = "不紧急不重要"

    var id: String { rawValue }

    var shortTitle: String {
        switch self {
        case .importantUrgent: "重要且紧急"
        case .importantNotUrgent: "重要不紧急"
        case .urgentNotImportant: "紧急不重要"
        case .notUrgentNotImportant: "不紧急不重要"
        }
    }

    static func from(isImportant: Bool, isUrgent: Bool) -> PriorityQuadrant {
        switch (isImportant, isUrgent) {
        case (true, true): .importantUrgent
        case (true, false): .importantNotUrgent
        case (false, true): .urgentNotImportant
        case (false, false): .notUrgentNotImportant
        }
    }
}
