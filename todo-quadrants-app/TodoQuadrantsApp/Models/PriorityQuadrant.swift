import Foundation
import SwiftUI

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

    var compactTitle: String {
        switch self {
        case .importantUrgent: "重急"
        case .importantNotUrgent: "重要"
        case .urgentNotImportant: "紧急"
        case .notUrgentNotImportant: "普通"
        }
    }

    var systemImage: String {
        switch self {
        case .importantUrgent: "flame.fill"
        case .importantNotUrgent: "target"
        case .urgentNotImportant: "bolt.fill"
        case .notUrgentNotImportant: "leaf.fill"
        }
    }

    var accentColor: Color {
        switch self {
        case .importantUrgent: Color(red: 0.93, green: 0.25, blue: 0.22)
        case .importantNotUrgent: Color(red: 0.12, green: 0.42, blue: 0.88)
        case .urgentNotImportant: Color(red: 0.91, green: 0.50, blue: 0.12)
        case .notUrgentNotImportant: Color(red: 0.20, green: 0.55, blue: 0.40)
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
