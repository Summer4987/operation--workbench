import Foundation
import SwiftData
import SwiftUI

struct ContentView: View {
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \TodoItem.updatedAt, order: .reverse) private var todos: [TodoItem]
    @State private var syncStatus = "准备同步"
    @State private var lastRemoteUpdatedAt = ""
    @State private var isApplyingRemote = false
    @State private var initialSyncDone = false
    private let syncTimer = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    syncStatusView
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
            .task {
                await pullRemoteTodos()
            }
            .onReceive(syncTimer) { _ in
                Task {
                    await pullRemoteTodos()
                }
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

    private var syncStatusView: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(syncStatus == "已同步" ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(syncStatus)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Button {
                Task {
                    await pullRemoteTodos(force: true)
                }
            } label: {
                Label("同步", systemImage: "arrow.triangle.2.circlepath")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.borderless)
            .help("同步")
        }
        .padding(.horizontal, 2)
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
            Task {
                await pushRemoteTodos()
            }
        } catch {
            assertionFailure("Failed to save todo: \(error)")
        }
    }

    @MainActor
    private func pushRemoteTodos() async {
        guard initialSyncDone, !isApplyingRemote else { return }
        do {
            syncStatus = "同步中..."
            let envelope = TodoSyncEnvelope(items: todos.map(TodoSyncItem.init(item:)))
            let saved = try await TodoSyncService.put(envelope)
            lastRemoteUpdatedAt = saved.updatedAt
            syncStatus = "已同步"
        } catch {
            syncStatus = "同步失败"
            print("Todo sync push failed: \(error)")
        }
    }

    @MainActor
    private func pullRemoteTodos(force: Bool = false) async {
        do {
            syncStatus = "同步中..."
            let remote = try await TodoSyncService.get()
            if remote.items.isEmpty, !todos.isEmpty, !initialSyncDone {
                initialSyncDone = true
                await pushRemoteTodos()
                return
            }
            if force || remote.updatedAt != lastRemoteUpdatedAt {
                applyRemoteTodos(remote.items)
                lastRemoteUpdatedAt = remote.updatedAt
            }
            initialSyncDone = true
            syncStatus = "已同步"
        } catch {
            initialSyncDone = true
            syncStatus = "离线保存"
            print("Todo sync pull failed: \(error)")
        }
    }

    @MainActor
    private func applyRemoteTodos(_ remoteItems: [TodoSyncItem]) {
        isApplyingRemote = true
        defer { isApplyingRemote = false }
        todos.forEach { modelContext.delete($0) }
        remoteItems.forEach { modelContext.insert($0.todoItem) }
        save()
    }
}

private struct TodoSyncEnvelope: Codable {
    var updatedAt: String
    var items: [TodoSyncItem]

    init(updatedAt: String = "", items: [TodoSyncItem]) {
        self.updatedAt = updatedAt
        self.items = items
    }

    enum CodingKeys: String, CodingKey {
        case updatedAt = "updated_at"
        case items
    }
}

private struct TodoSyncItem: Codable {
    var id: UUID
    var title: String
    var category: String
    var quadrant: String
    var isCompleted: Bool
    var createdAt: String
    var updatedAt: String
    var completedAt: String

    init(item: TodoItem) {
        self.id = item.id
        self.title = item.title
        self.category = item.category.syncValue
        self.quadrant = item.quadrant.syncValue
        self.isCompleted = item.isCompleted
        self.createdAt = TodoSyncService.formatter.string(from: item.createdAt)
        self.updatedAt = TodoSyncService.formatter.string(from: item.updatedAt)
        self.completedAt = item.completedAt.map { TodoSyncService.formatter.string(from: $0) } ?? ""
    }

    var todoItem: TodoItem {
        TodoItem(
            id: id,
            title: title,
            category: TodoCategory(syncValue: category),
            quadrant: PriorityQuadrant(syncValue: quadrant),
            isCompleted: isCompleted,
            createdAt: TodoSyncService.parseDate(createdAt),
            updatedAt: TodoSyncService.parseDate(updatedAt),
            completedAt: TodoSyncService.parseOptionalDate(completedAt)
        )
    }

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case category
        case quadrant
        case isCompleted = "is_completed"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
    }
}

private enum TodoSyncService {
    static let formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static func get() async throws -> TodoSyncEnvelope {
        let (data, response) = try await URLSession.shared.data(from: AppConstants.todoSyncURL)
        try validate(response)
        return try decoder.decode(TodoSyncEnvelope.self, from: data)
    }

    static func put(_ envelope: TodoSyncEnvelope) async throws -> TodoSyncEnvelope {
        var request = URLRequest(url: AppConstants.todoSyncURL)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(envelope)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        return try decoder.decode(TodoSyncEnvelope.self, from: data)
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        return decoder
    }()

    private static func validate(_ response: URLResponse) throws {
        guard let response = response as? HTTPURLResponse, 200..<300 ~= response.statusCode else {
            throw URLError(.badServerResponse)
        }
    }

    static func parseDate(_ value: String) -> Date {
        parseOptionalDate(value) ?? .now
    }

    static func parseOptionalDate(_ value: String) -> Date? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return formatter.date(from: trimmed) ?? ISO8601DateFormatter().date(from: trimmed)
    }
}

private extension TodoCategory {
    init(syncValue: String) {
        switch syncValue {
        case "directStores", "直营门店": self = .directStores
        case "franchise", "加盟业务": self = .franchise
        case "supplyChain", "供应链": self = .supplyChain
        case "ai", "AI": self = .ai
        default: self = .platform
        }
    }

    var syncValue: String {
        switch self {
        case .platform: "platform"
        case .directStores: "directStores"
        case .franchise: "franchise"
        case .supplyChain: "supplyChain"
        case .ai: "ai"
        }
    }
}

private extension PriorityQuadrant {
    init(syncValue: String) {
        switch syncValue {
        case "importantNotUrgent", "重要不紧急": self = .importantNotUrgent
        case "urgentNotImportant", "紧急不重要": self = .urgentNotImportant
        case "notUrgentNotImportant", "notImportantNotUrgent", "不紧急不重要": self = .notUrgentNotImportant
        default: self = .importantUrgent
        }
    }

    var syncValue: String {
        switch self {
        case .importantUrgent: "importantUrgent"
        case .importantNotUrgent: "importantNotUrgent"
        case .urgentNotImportant: "urgentNotImportant"
        case .notUrgentNotImportant: "notUrgentNotImportant"
        }
    }
}
