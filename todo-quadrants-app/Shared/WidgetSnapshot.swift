import Foundation

struct WidgetTodo: Identifiable, Codable, Hashable {
    var id: UUID
    var title: String
    var category: String
    var quadrant: String
}

struct WidgetSnapshot: Codable, Hashable {
    var updatedAt: Date
    var importantUrgent: [WidgetTodo]
    var importantNotUrgent: [WidgetTodo]
    var urgentNotImportant: [WidgetTodo]
    var notUrgentNotImportant: [WidgetTodo]

    static let empty = WidgetSnapshot(
        updatedAt: .now,
        importantUrgent: [],
        importantNotUrgent: [],
        urgentNotImportant: [],
        notUrgentNotImportant: []
    )
}
