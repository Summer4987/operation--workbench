import Foundation
import WidgetKit

enum WidgetSnapshotWriter {
    static func write(items: [TodoItem]) {
        guard let url = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: AppConstants.appGroupIdentifier)?
            .appendingPathComponent(AppConstants.widgetSnapshotFileName) else {
            return
        }

        let activeItems = items.filter { !$0.isCompleted }
        let snapshot = WidgetSnapshot(
            updatedAt: .now,
            importantUrgent: widgetTodos(activeItems, in: .importantUrgent),
            importantNotUrgent: widgetTodos(activeItems, in: .importantNotUrgent),
            urgentNotImportant: widgetTodos(activeItems, in: .urgentNotImportant),
            notUrgentNotImportant: widgetTodos(activeItems, in: .notUrgentNotImportant)
        )

        do {
            let data = try JSONEncoder.widgetEncoder.encode(snapshot)
            try data.write(to: url, options: [.atomic])
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            assertionFailure("Failed to write widget snapshot: \(error)")
        }
    }

    private static func widgetTodos(_ items: [TodoItem], in quadrant: PriorityQuadrant) -> [WidgetTodo] {
        items
            .filter { $0.quadrant == quadrant }
            .sorted { $0.updatedAt > $1.updatedAt }
            .prefix(6)
            .map { WidgetTodo(id: $0.id, title: $0.title, category: $0.category.rawValue, quadrant: $0.quadrant.rawValue) }
    }
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
