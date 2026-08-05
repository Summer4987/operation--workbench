import SwiftData
import SwiftUI

struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \TodoItem.updatedAt, order: .reverse) private var todos: [TodoItem]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    QuadrantGridView(items: activeTodos, onToggle: toggle)
                    CategoryComposerView(onAdd: addTodo)
                    CompletedListView(items: completedTodos, onToggle: toggle, onDelete: delete)
                }
                .padding()
            }
            .background(pageBackground)
            .navigationTitle("待办")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .task(id: snapshotToken) {
                WidgetSnapshotWriter.write(items: todos)
            }
        }
    }

    private var activeTodos: [TodoItem] {
        todos.filter { !$0.isCompleted }
    }

    private var completedTodos: [TodoItem] {
        todos
            .filter(\.isCompleted)
            .sorted { ($0.completedAt ?? $0.updatedAt) > ($1.completedAt ?? $1.updatedAt) }
    }

    private var snapshotToken: String {
        todos
            .map { "\($0.id.uuidString)-\($0.updatedAt.timeIntervalSince1970)-\($0.isCompleted)" }
            .joined(separator: "|")
    }

    private var pageBackground: Color {
        #if os(iOS)
        Color(.systemGroupedBackground)
        #elseif os(macOS)
        Color(nsColor: .windowBackgroundColor)
        #else
        Color(.background)
        #endif
    }

    private func addTodo(title: String, category: TodoCategory, isImportant: Bool, isUrgent: Bool) {
        let item = TodoItem(
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            category: category,
            quadrant: .from(isImportant: isImportant, isUrgent: isUrgent)
        )
        modelContext.insert(item)
        save()
    }

    private func toggle(_ item: TodoItem) {
        item.setCompleted(!item.isCompleted)
        save()
    }

    private func delete(_ item: TodoItem) {
        modelContext.delete(item)
        save()
    }

    private func save() {
        do {
            try modelContext.save()
            WidgetSnapshotWriter.write(items: todos)
        } catch {
            assertionFailure("Failed to save todo: \(error)")
        }
    }
}
