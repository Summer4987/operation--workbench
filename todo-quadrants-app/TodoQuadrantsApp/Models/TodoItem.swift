import Foundation
import SwiftData

@Model
final class TodoItem {
    var id: UUID = UUID()
    var title: String = ""
    var categoryRawValue: String = TodoCategory.platform.rawValue
    var quadrantRawValue: String = PriorityQuadrant.importantUrgent.rawValue
    var isCompleted: Bool = false
    var createdAt: Date = Date()
    var updatedAt: Date = Date()
    var completedAt: Date?

    init(
        id: UUID = UUID(),
        title: String,
        category: TodoCategory,
        quadrant: PriorityQuadrant,
        isCompleted: Bool = false,
        createdAt: Date = .now,
        updatedAt: Date = .now,
        completedAt: Date? = nil
    ) {
        self.id = id
        self.title = title
        self.categoryRawValue = category.rawValue
        self.quadrantRawValue = quadrant.rawValue
        self.isCompleted = isCompleted
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.completedAt = completedAt
    }

    var category: TodoCategory {
        get { TodoCategory(rawValue: categoryRawValue) ?? .platform }
        set {
            categoryRawValue = newValue.rawValue
            updatedAt = .now
        }
    }

    var quadrant: PriorityQuadrant {
        get { PriorityQuadrant(rawValue: quadrantRawValue) ?? .importantUrgent }
        set {
            quadrantRawValue = newValue.rawValue
            updatedAt = .now
        }
    }

    func setCompleted(_ completed: Bool) {
        isCompleted = completed
        completedAt = completed ? .now : nil
        updatedAt = .now
    }
}
