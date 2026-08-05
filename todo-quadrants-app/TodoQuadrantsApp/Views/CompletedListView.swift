import SwiftUI

struct CompletedListView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    let onDelete: (TodoItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("已完成")
                    .font(.headline)
                Spacer()
                Text("\(items.count)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if items.isEmpty {
                Text("还没有完成项")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 10)
            } else {
                VStack(spacing: 8) {
                    ForEach(items) { item in
                        CompletedTodoRow(item: item, onToggle: onToggle, onDelete: onDelete)
                    }
                }
            }
        }
        .padding(12)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.secondary.opacity(0.12), lineWidth: 1)
        )
    }
}

private struct CompletedTodoRow: View {
    let item: TodoItem
    let onToggle: (TodoItem) -> Void
    let onDelete: (TodoItem) -> Void

    var body: some View {
        HStack(spacing: 10) {
            Button {
                onToggle(item)
            } label: {
                Image(systemName: "checkmark.square.fill")
                    .foregroundStyle(.green)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.subheadline)
                    .strikethrough()
                    .foregroundStyle(.secondary)
                Text("\(item.category.rawValue) · \(item.quadrant.shortTitle)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button(role: .destructive) {
                onDelete(item)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.plain)
        }
        .padding(8)
        .background(Color.secondary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
