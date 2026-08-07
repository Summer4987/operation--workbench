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
    @State private var memoText = ""
    private let syncTimer = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    headerView
                    QuadrantGridView(items: activeTodos, onToggle: toggle)
                    CategoryComposerView(onAdd: addTodo)
                    MemoPadView(text: $memoText, onSave: saveMemo)
                    CompletedListView(items: completedTodos, onToggle: toggle, onDelete: delete)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 18)
                .frame(maxWidth: 980, alignment: .topLeading)
                .frame(maxWidth: .infinity)
            }
            .background(pageBackground)
            .navigationTitle("")
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
        Color(red: 0.96, green: 0.97, blue: 0.98)
        #elseif os(macOS)
        Color(red: 0.96, green: 0.97, blue: 0.98)
        #else
        Color(.background)
        #endif
    }

    private var headerView: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("今日待办")
                        .font(.title.bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text(summaryText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Spacer()

                syncButton
            }

            HStack(spacing: 10) {
                MetricPill(title: "待处理", value: "\(activeTodos.count)", color: .blue)
                MetricPill(title: "已完成", value: "\(completedTodos.count)", color: .green)
                MetricPill(title: "重急", value: "\(count(for: .importantUrgent))", color: PriorityQuadrant.importantUrgent.accentColor)
            }
        }
        .padding(16)
        .background(
            LinearGradient(
                colors: [Color.white, Color(red: 0.91, green: 0.94, blue: 0.98)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.white.opacity(0.8), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.05), radius: 14, x: 0, y: 6)
    }

    private var syncButton: some View {
        Button {
            Task {
                await pullRemoteTodos(force: true)
            }
        } label: {
            HStack(spacing: 7) {
                Circle()
                    .fill(syncStatus == "已同步" ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(syncStatus)
                    .font(.caption2.weight(.semibold))
                    .lineLimit(1)
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.caption2.weight(.semibold))
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.86))
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .help("同步")
    }

    private var summaryText: String {
        if activeTodos.isEmpty {
            return "没有待处理事项，保持干净。"
        }
        let urgentCount = count(for: .importantUrgent) + count(for: .urgentNotImportant)
        if urgentCount > 0 {
            return "\(urgentCount) 项紧急事项需要优先看。"
        }
        return "\(activeTodos.count) 项待办，暂无紧急事项。"
    }

    private func count(for quadrant: PriorityQuadrant) -> Int {
        activeTodos.filter { $0.quadrant == quadrant }.count
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
            let envelope = TodoSyncEnvelope(items: todos.map(TodoSyncItem.init(item:)), memo: memoText)
            let saved = try await TodoSyncService.put(envelope)
            lastRemoteUpdatedAt = saved.updatedAt
            memoText = saved.memo
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
                memoText = remote.memo
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

    private func saveMemo() {
        Task {
            await pushRemoteTodos()
        }
    }
}

private struct MemoPadView: View {
    @Binding var text: String
    let onSave: () -> Void
    @FocusState private var isFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "备忘录", subtitle: "随手记录，不进四象限")

            TextEditor(text: $text)
                .focused($isFocused)
                .font(.body)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 96)
                .padding(10)
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(alignment: .topLeading) {
                    if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isFocused {
                        Text("临时想法、采购提醒、会议记录...")
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 18)
                            .allowsHitTesting(false)
                    }
                }
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.secondary.opacity(0.10), lineWidth: 1)
        )
        .onChange(of: isFocused) { _, focused in
            if !focused {
                onSave()
            }
        }
    }
}

private struct MetricPill: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Text(value)
                .font(.headline.weight(.bold))
                .foregroundStyle(color)
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(Color.white.opacity(0.75))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct TodoSyncEnvelope: Codable {
    var updatedAt: String
    var items: [TodoSyncItem]
    var memo: String

    init(updatedAt: String = "", items: [TodoSyncItem], memo: String = "") {
        self.updatedAt = updatedAt
        self.items = items
        self.memo = memo
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt) ?? ""
        items = try container.decodeIfPresent([TodoSyncItem].self, forKey: .items) ?? []
        memo = try container.decodeIfPresent(String.self, forKey: .memo) ?? ""
    }

    enum CodingKeys: String, CodingKey {
        case updatedAt = "updated_at"
        case items
        case memo
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
