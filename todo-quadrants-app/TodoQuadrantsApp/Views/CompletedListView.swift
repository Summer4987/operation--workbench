import SwiftUI

struct CompletedListView: View {
    let items: [TodoItem]
    let onToggle: (TodoItem) -> Void
    let onDelete: (TodoItem) -> Void
    let onDeleteAll: () -> Void

    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: verticalSpacing) {
            HStack(spacing: 10) {
                Button {
                    withAnimation(.spring(response: 0.24, dampingFraction: 0.9)) {
                        isExpanded.toggle()
                    }
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("已完成")
                                .font(titleFont)
                            Text(items.isEmpty ? "完成后会收纳到这里" : "\(items.count) 项已归档")
                                .font(subtitleFont)
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

                if !items.isEmpty {
                    Button(role: .destructive) {
                        onDeleteAll()
                    } label: {
                        Image(systemName: "trash")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.red.opacity(0.86))
                            .frame(width: deleteButtonSize, height: deleteButtonSize)
                            .background(Color.red.opacity(0.10))
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .help("清空已完成")
                }
            }

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
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title)
                            .font(rowTitleFont)
                            .lineLimit(1)
                            .foregroundStyle(.secondary)
                        if items.count > 1 {
                            Text("另有 \(items.count - 1) 项，点上方展开查看")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
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
        .padding(cardPadding)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.secondary.opacity(0.10), lineWidth: 1)
        )
    }

    private var verticalSpacing: CGFloat {
        #if os(iOS)
        8
        #else
        10
        #endif
    }

    private var cardPadding: CGFloat {
        #if os(iOS)
        12
        #else
        16
        #endif
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

    private var rowTitleFont: Font {
        #if os(iOS)
        .caption.weight(.medium)
        #else
        .subheadline
        #endif
    }

    private var deleteButtonSize: CGFloat {
        #if os(iOS)
        30
        #else
        34
        #endif
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
