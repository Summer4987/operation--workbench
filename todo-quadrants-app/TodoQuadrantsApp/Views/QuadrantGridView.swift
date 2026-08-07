import SwiftUI

struct QuadrantGridView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    @State private var selectedQuadrant: PriorityQuadrant?

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
                        onToggle: onToggle,
                        onOpen: {
                            selectedQuadrant = quadrant
                        }
                    )
                    .frame(minHeight: 132, maxHeight: 164)
                }
            }
        }
        .sheet(item: $selectedQuadrant) { quadrant in
            QuadrantDetailView(
                quadrant: quadrant,
                items: itemsFor(quadrant),
                onToggle: onToggle
            )
            #if os(iOS)
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            #endif
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
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .center, spacing: 7) {
                Image(systemName: quadrant.systemImage)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(quadrant.accentColor)
                    .frame(width: 20, height: 20)
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

            if items.isEmpty {
                Spacer()
                Text("暂无事项")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                Spacer()
            } else {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(items.prefix(2)) { item in
                        TodoMiniRow(item: item, accentColor: quadrant.accentColor, onToggle: onToggle)
                    }
                    if items.count > 2 {
                        Button(action: onOpen) {
                            HStack(spacing: 4) {
                                Text("还有 \(items.count - 2) 项")
                                Image(systemName: "chevron.right")
                            }
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(quadrant.accentColor)
                            .padding(.top, 2)
                        }
                        .buttonStyle(.plain)
                    } else if !items.isEmpty {
                        Button(action: onOpen) {
                            HStack(spacing: 4) {
                                Text("查看全部")
                                Image(systemName: "chevron.right")
                            }
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(quadrant.accentColor)
                            .padding(.top, 2)
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(
            LinearGradient(
                colors: [Color.white, quadrant.accentColor.opacity(0.08)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(quadrant.accentColor.opacity(0.16), lineWidth: 1)
        )
        .shadow(color: quadrant.accentColor.opacity(0.07), radius: 8, x: 0, y: 4)
    }
}

private struct QuadrantDetailView: View {
    let quadrant: PriorityQuadrant
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 10) {
                        Image(systemName: quadrant.systemImage)
                            .font(.headline.weight(.bold))
                            .foregroundStyle(quadrant.accentColor)
                            .frame(width: 34, height: 34)
                            .background(quadrant.accentColor.opacity(0.12))
                            .clipShape(Circle())

                        VStack(alignment: .leading, spacing: 2) {
                            Text(quadrant.shortTitle)
                                .font(.title3.weight(.bold))
                            Text("\(items.count) 项待办")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.bottom, 4)

                    if items.isEmpty {
                        Text("这个象限暂无事项")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 28)
                    } else {
                        VStack(spacing: 8) {
                            ForEach(items) { item in
                                QuadrantDetailRow(item: item, accentColor: quadrant.accentColor, onToggle: onToggle)
                            }
                        }
                    }
                }
                .padding(18)
            }
            .background(Color(red: 0.96, green: 0.97, blue: 0.98))
            .navigationTitle("全部待办")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        }
    }
}

private struct QuadrantDetailRow: View {
    let item: TodoItem
    let accentColor: Color
    let onToggle: (TodoItem) -> Void

    var body: some View {
        Button {
            onToggle(item)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "square")
                    .font(.title3)
                    .foregroundStyle(accentColor)
                    .frame(width: 24)

                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)

                    Text(item.category.rawValue)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }
            .padding(12)
            .background(Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(accentColor.opacity(0.12), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
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
