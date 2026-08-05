import SwiftUI

struct QuadrantGridView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void

    private let columns = [
        GridItem(.flexible(), spacing: 10),
        GridItem(.flexible(), spacing: 10),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("四象限")
                .font(.headline)

            LazyVGrid(columns: columns, spacing: 10) {
                ForEach(PriorityQuadrant.allCases) { quadrant in
                    QuadrantCard(
                        title: quadrant.shortTitle,
                        items: itemsFor(quadrant),
                        onToggle: onToggle
                    )
                    .aspectRatio(1, contentMode: .fit)
                }
            }
        }
    }

    private func itemsFor(_ quadrant: PriorityQuadrant) -> [TodoItem] {
        items
            .filter { $0.quadrant == quadrant }
            .sorted { $0.updatedAt > $1.updatedAt }
    }
}

private struct QuadrantCard: View {
    let title: String
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text("\(items.count)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            Divider()

            if items.isEmpty {
                Spacer()
                Text("空")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(items) { item in
                            TodoMiniRow(item: item, onToggle: onToggle)
                        }
                    }
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 1)
        )
    }
}

private struct TodoMiniRow: View {
    let item: TodoItem
    let onToggle: (TodoItem) -> Void

    var body: some View {
        Button {
            onToggle(item)
        } label: {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "square")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title)
                        .font(.caption)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    Text(item.category.rawValue)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
    }
}
