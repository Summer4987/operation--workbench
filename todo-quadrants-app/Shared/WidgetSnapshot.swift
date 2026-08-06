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

extension JSONEncoder {
    static var widgetEncoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

extension JSONDecoder {
    static var widgetDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}
