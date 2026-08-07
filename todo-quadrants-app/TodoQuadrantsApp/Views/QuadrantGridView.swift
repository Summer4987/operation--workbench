import SwiftUI

struct QuadrantGridView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void

    private let columns = [
        GridItem(.flexible(), spacing: 12),
        GridItem(.flexible(), spacing: 12),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "优先级矩阵", subtitle: "自动按重要 / 紧急归位")

            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(PriorityQuadrant.allCases) { quadrant in
                    QuadrantCard(
                        quadrant: quadrant,
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
    let quadrant: PriorityQuadrant
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .center, spacing: 7) {
                Image(systemName: quadrant.systemImage)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(quadrant.accentColor)
                    .frame(width: 22, height: 22)
                    .background(quadrant.accentColor.opacity(0.12))
                    .clipShape(Circle())

                Text(quadrant.shortTitle)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .minimumScaleFactor(0.86)

                Spacer()

                Text("\(items.count)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(quadrant.accentColor)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(quadrant.accentColor.opacity(0.12))
                    .clipShape(Capsule())
            }

            Rectangle()
                .fill(quadrant.accentColor.opacity(0.2))
                .frame(height: 1)

            if items.isEmpty {
                Spacer()
                Text("暂无事项")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                Spacer()
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(items.prefix(3)) { item in
                        TodoMiniRow(item: item, accentColor: quadrant.accentColor, onToggle: onToggle)
                    }
                    if items.count > 3 {
                        Text("还有 \(items.count - 3) 项")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(quadrant.accentColor)
                            .padding(.top, 2)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(
            LinearGradient(
                colors: [Color.white, quadrant.accentColor.opacity(0.08)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(quadrant.accentColor.opacity(0.16), lineWidth: 1)
        )
        .shadow(color: quadrant.accentColor.opacity(0.08), radius: 10, x: 0, y: 5)
    }
}

private struct TodoMiniRow: View {
    let item: TodoItem
    let accentColor: Color
    let onToggle: (TodoItem) -> Void

    var body: some View {
        Button {
            onToggle(item)
        } label: {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "square")
                    .font(.caption)
                    .foregroundStyle(accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title)
                        .font(.caption.weight(.medium))
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

struct SectionHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.headline.weight(.bold))
            Spacer()
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
    }
}
