import SwiftUI

struct QuadrantGridView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    @State private var selectedQuadrant: PriorityQuadrant?

    private var columns: [GridItem] {
        [
            GridItem(.flexible(), spacing: gridSpacing),
            GridItem(.flexible(), spacing: gridSpacing),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: sectionSpacing) {
            SectionHeader(title: "优先级矩阵", subtitle: "自动按重要 / 紧急归位")

            LazyVGrid(columns: columns, spacing: gridSpacing) {
                ForEach(PriorityQuadrant.allCases) { quadrant in
                    QuadrantCard(
                        quadrant: quadrant,
                        items: itemsFor(quadrant),
                        onToggle: onToggle,
                        onOpen: {
                            selectedQuadrant = quadrant
                        }
                    )
                    .frame(minHeight: cardMinHeight, maxHeight: cardMaxHeight)
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

    private var sectionSpacing: CGFloat {
        #if os(iOS)
        10
        #else
        12
        #endif
    }

    private var gridSpacing: CGFloat {
        #if os(iOS)
        10
        #else
        12
        #endif
    }

    private var cardMinHeight: CGFloat {
        #if os(iOS)
        140
        #else
        132
        #endif
    }

    private var cardMaxHeight: CGFloat {
        #if os(iOS)
        172
        #else
        164
        #endif
    }
}

private struct QuadrantCard: View {
    let quadrant: PriorityQuadrant
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: verticalSpacing) {
            HStack(alignment: .center, spacing: 6) {
                Image(systemName: quadrant.systemImage)
                    .font(iconFont)
                    .foregroundStyle(quadrant.accentColor)
                    .frame(width: iconBoxSize, height: iconBoxSize)
                    .background(quadrant.accentColor.opacity(0.12))
                    .clipShape(Circle())

                Text(quadrant.shortTitle)
                    .font(titleFont)
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .minimumScaleFactor(0.86)

                Spacer()

                Text("\(items.count)")
                    .font(countFont)
                    .foregroundStyle(quadrant.accentColor)
                    .padding(.horizontal, countHorizontalPadding)
                    .padding(.vertical, countVerticalPadding)
                    .background(quadrant.accentColor.opacity(0.12))
                    .clipShape(Capsule())
            }

            if items.isEmpty {
                Spacer()
                Text("暂无事项")
                    .font(emptyFont)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                Spacer()
            } else {
                VStack(alignment: .leading, spacing: rowSpacing) {
                    ForEach(items.prefix(previewLimit)) { item in
                        TodoMiniRow(item: item, accentColor: quadrant.accentColor, onToggle: onToggle)
                    }
                    if items.count > previewLimit {
                        Button(action: onOpen) {
                            HStack(spacing: 4) {
                                Text("还有 \(items.count - previewLimit) 项")
                                Image(systemName: "chevron.right")
                            }
                            .font(linkFont)
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
                            .font(linkFont)
                            .foregroundStyle(quadrant.accentColor)
                            .padding(.top, 2)
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(cardPadding)
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
        .shadow(color: quadrant.accentColor.opacity(0.06), radius: shadowRadius, x: 0, y: shadowY)
    }

    private var previewLimit: Int {
        #if os(iOS)
        3
        #else
        2
        #endif
    }

    private var verticalSpacing: CGFloat {
        #if os(iOS)
        7
        #else
        7
        #endif
    }

    private var rowSpacing: CGFloat {
        #if os(iOS)
        5
        #else
        5
        #endif
    }

    private var cardPadding: CGFloat {
        #if os(iOS)
        9
        #else
        10
        #endif
    }

    private var iconBoxSize: CGFloat {
        #if os(iOS)
        20
        #else
        20
        #endif
    }

    private var iconFont: Font {
        #if os(iOS)
        .caption2.weight(.bold)
        #else
        .caption.weight(.bold)
        #endif
    }

    private var titleFont: Font {
        #if os(iOS)
        .caption.weight(.bold)
        #else
        .caption.weight(.bold)
        #endif
    }

    private var countFont: Font {
        #if os(iOS)
        .caption2.weight(.bold)
        #else
        .caption.weight(.bold)
        #endif
    }

    private var emptyFont: Font {
        #if os(iOS)
        .caption2
        #else
        .caption
        #endif
    }

    private var linkFont: Font {
        #if os(iOS)
        .caption2.weight(.bold)
        #else
        .caption2.weight(.semibold)
        #endif
    }

    private var countHorizontalPadding: CGFloat {
        #if os(iOS)
        6
        #else
        7
        #endif
    }

    private var countVerticalPadding: CGFloat {
        #if os(iOS)
        2
        #else
        3
        #endif
    }

    private var shadowRadius: CGFloat {
        #if os(iOS)
        5
        #else
        8
        #endif
    }

    private var shadowY: CGFloat {
        #if os(iOS)
        2
        #else
        4
        #endif
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
                        .font(miniTitleFont)
                        .lineLimit(miniTitleLineLimit)
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

    private var miniTitleFont: Font {
        #if os(iOS)
        .caption.weight(.medium)
        #else
        .caption.weight(.medium)
        #endif
    }

    private var miniTitleLineLimit: Int {
        #if os(iOS)
        2
        #else
        2
        #endif
    }
}

struct SectionHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(titleFont)
            Spacer()
            Text(subtitle)
                .font(subtitleFont)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
    }

    private var titleFont: Font {
        #if os(iOS)
        .subheadline.weight(.bold)
        #else
        .headline.weight(.bold)
        #endif
    }

    private var subtitleFont: Font {
        #if os(iOS)
        .caption2
        #else
        .caption
        #endif
    }
}
