import SwiftUI

struct CategoryComposerView: View {
    let onAdd: (_ title: String, _ category: TodoCategory, _ isImportant: Bool, _ isUrgent: Bool) -> Void

    @State private var draft = ""
    @State private var selectedCategory: TodoCategory = .platform
    @State private var isImportant = true
    @State private var isUrgent = true

    var body: some View {
        VStack(alignment: .leading, spacing: cardSpacing) {
            SectionHeader(title: "快速添加", subtitle: "选择分类和优先级")

            VStack(alignment: .leading, spacing: innerSpacing) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(TodoCategory.allCases) { category in
                            CategoryChip(
                                category: category,
                                isSelected: selectedCategory == category
                            ) {
                                selectedCategory = category
                            }
                        }
                    }
                    .padding(.vertical, 1)
                }

                HStack(spacing: 10) {
                    Image(systemName: selectedCategory.systemImage)
                        .foregroundStyle(.secondary)
                        .frame(width: leadingIconWidth)

                    TextField("输入待办", text: $draft)
                        .textFieldStyle(.plain)
                        .font(inputFont)
                        .submitLabel(.done)
                        .onSubmit(add)

                    HStack(spacing: 6) {
                        ToggleChip(title: "重要", systemImage: "star.fill", color: Color(red: 0.48, green: 0.24, blue: 0.84), isOn: $isImportant)
                        ToggleChip(title: "紧急", systemImage: "clock.fill", color: Color(red: 0.84, green: 0.20, blue: 0.45), isOn: $isUrgent)
                    }

                    Button {
                        add()
                    } label: {
                        Image(systemName: "plus")
                            .font(addButtonFont)
                            .foregroundStyle(.white)
                            .frame(width: addButtonSize, height: addButtonSize)
                            .background(trimmedDraft.isEmpty ? Color.secondary.opacity(0.35) : Color.blue)
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(trimmedDraft.isEmpty)
                }
                .padding(.horizontal, inputHorizontalPadding)
                .padding(.vertical, inputVerticalPadding)
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
        }
        .padding(cardPadding)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.secondary.opacity(0.10), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.04), radius: 12, x: 0, y: 5)
    }

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func add() {
        let title = trimmedDraft
        guard !title.isEmpty else { return }
        onAdd(title, selectedCategory, isImportant, isUrgent)
        draft = ""
    }

    private var cardSpacing: CGFloat {
        #if os(iOS)
        10
        #else
        14
        #endif
    }

    private var innerSpacing: CGFloat {
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

    private var leadingIconWidth: CGFloat {
        #if os(iOS)
        18
        #else
        22
        #endif
    }

    private var inputFont: Font {
        #if os(iOS)
        .subheadline
        #else
        .body
        #endif
    }

    private var addButtonFont: Font {
        #if os(iOS)
        .subheadline.weight(.bold)
        #else
        .headline.weight(.bold)
        #endif
    }

    private var addButtonSize: CGFloat {
        #if os(iOS)
        30
        #else
        34
        #endif
    }

    private var inputHorizontalPadding: CGFloat {
        #if os(iOS)
        10
        #else
        12
        #endif
    }

    private var inputVerticalPadding: CGFloat {
        #if os(iOS)
        9
        #else
        11
        #endif
    }
}

private struct CategoryChip: View {
    let category: TodoCategory
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(category.rawValue, systemImage: category.systemImage)
                .font(chipFont)
                .labelStyle(.titleAndIcon)
                .foregroundStyle(isSelected ? Color.white : Color.primary)
                .padding(.horizontal, horizontalPadding)
                .padding(.vertical, verticalPadding)
                .background(isSelected ? Color.blue : Color.secondary.opacity(0.08))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private var chipFont: Font {
        #if os(iOS)
        .caption2.weight(.semibold)
        #else
        .caption.weight(.semibold)
        #endif
    }

    private var horizontalPadding: CGFloat {
        #if os(iOS)
        10
        #else
        11
        #endif
    }

    private var verticalPadding: CGFloat {
        #if os(iOS)
        7
        #else
        8
        #endif
    }
}

private struct ToggleChip: View {
    let title: String
    let systemImage: String
    let color: Color
    @Binding var isOn: Bool

    var body: some View {
        Button {
            isOn.toggle()
        } label: {
            Label(title, systemImage: systemImage)
                .font(.caption.weight(.bold))
                .foregroundStyle(isOn ? Color.white : color)
                .labelStyle(.iconOnly)
                .frame(width: buttonSize, height: buttonSize)
                .background(isOn ? color : color.opacity(0.12))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .help(title)
    }

    private var buttonSize: CGFloat {
        #if os(iOS)
        28
        #else
        30
        #endif
    }
}
