import SwiftUI
import WidgetKit

struct TodoEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct TodoProvider: TimelineProvider {
    func placeholder(in context: Context) -> TodoEntry {
        TodoEntry(date: .now, snapshot: .empty)
    }

    func getSnapshot(in context: Context, completion: @escaping (TodoEntry) -> Void) {
        completion(TodoEntry(date: .now, snapshot: readSnapshot()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodoEntry>) -> Void) {
        let entry = TodoEntry(date: .now, snapshot: readSnapshot())
        completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(15 * 60))))
    }

    private func readSnapshot() -> WidgetSnapshot {
        guard let url = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: AppConstants.appGroupIdentifier)?
            .appendingPathComponent(AppConstants.widgetSnapshotFileName),
            let data = try? Data(contentsOf: url),
            let snapshot = try? JSONDecoder.widgetDecoder.decode(WidgetSnapshot.self, from: data)
        else {
            return .empty
        }
        return snapshot
    }
}

struct TodoQuadrantsWidgetView: View {
    let entry: TodoEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("待办")
                    .font(.headline)
                Spacer()
                Text(entry.snapshot.updatedAt, style: .time)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            QuadrantCountGrid(snapshot: entry.snapshot)

            Divider()

            VStack(alignment: .leading, spacing: 4) {
                ForEach(entry.snapshot.importantUrgent.prefix(3)) { item in
                    HStack(spacing: 5) {
                        Image(systemName: "square")
                            .font(.caption2)
                        Text(item.title)
                            .font(.caption)
                            .lineLimit(1)
                    }
                }
                if entry.snapshot.importantUrgent.isEmpty {
                    Text("暂无重要且紧急")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .containerBackground(.background, for: .widget)
    }
}

private struct QuadrantCountGrid: View {
    let snapshot: WidgetSnapshot

    private var counts: [(String, Int)] {
        [
            ("重急", snapshot.importantUrgent.count),
            ("重缓", snapshot.importantNotUrgent.count),
            ("急轻", snapshot.urgentNotImportant.count),
            ("轻缓", snapshot.notUrgentNotImportant.count),
        ]
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 4) {
            ForEach(counts, id: \.0) { title, count in
                HStack {
                    Text(title)
                    Spacer()
                    Text("\(count)")
                        .fontWeight(.semibold)
                }
                .font(.caption2)
                .padding(6)
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
    }
}

@main
struct TodoQuadrantsWidget: Widget {
    let kind = "TodoQuadrantsWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TodoProvider()) { entry in
            TodoQuadrantsWidgetView(entry: entry)
        }
        .configurationDisplayName("待办四象限")
        .description("查看重要且紧急待办和四象限数量。")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
