import SwiftUI

struct CompletedListView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    let onDelete: (TodoItem) -> Void

    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.9)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("已完成")
                            .font(.headline.weight(.bold))
                        Text(items.isEmpty ? "完成后会收纳到这里" : "\(items.count) 项已归档")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Image(systemName: "chevron.down")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
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
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            } else if let item = items.first {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text(item.title)
                        .font(.subheadline)
                        .lineLimit(1)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(10)
                .background(Color.secondary.opacity(0.06))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
        .padding(16)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.secondary.opacity(0.10), lineWidth: 1)
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
                    .font(.title3)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.subheadline.weight(.medium))
                    .strikethrough()
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Text("\(item.category.rawValue) · \(item.quadrant.shortTitle)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button(role: .destructive) {
                onDelete(item)
            } label: {
                Image(systemName: "trash")
                    .foregroundStyle(.red.opacity(0.82))
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .background(Color.secondary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
