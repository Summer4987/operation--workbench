import SwiftUI

struct CategoryComposerView: View {
    let onAdd: (_ title: String, _ category: TodoCategory, _ isImportant: Bool, _ isUrgent: Bool) -> Void

    @State private var draft = ""
    @State private var selectedCategory: TodoCategory = .platform
    @State private var isImportant = true
    @State private var isUrgent = true

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "快速添加", subtitle: "选择分类和优先级")

            VStack(alignment: .leading, spacing: 10) {
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

                HStack(spacing: 8) {
                    ToggleChip(title: "重要", systemImage: "star.fill", color: .blue, isOn: $isImportant)
                    ToggleChip(title: "紧急", systemImage: "clock.fill", color: .orange, isOn: $isUrgent)
                }

                HStack(spacing: 10) {
                    Image(systemName: selectedCategory.systemImage)
                        .foregroundStyle(.secondary)
                        .frame(width: 22)

                    TextField("输入待办", text: $draft)
                        .textFieldStyle(.plain)
                        .submitLabel(.done)
                        .onSubmit(add)

                    Button {
                        add()
                    } label: {
                        Image(systemName: "plus")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(.white)
                            .frame(width: 34, height: 34)
                            .background(trimmedDraft.isEmpty ? Color.secondary.opacity(0.35) : Color.blue)
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(trimmedDraft.isEmpty)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(Color.secondary.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
        }
        .padding(16)
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
}

private struct CategoryChip: View {
    let category: TodoCategory
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(category.rawValue, systemImage: category.systemImage)
                .font(.caption.weight(.semibold))
                .labelStyle(.titleAndIcon)
                .foregroundStyle(isSelected ? Color.white : Color.primary)
                .padding(.horizontal, 11)
                .padding(.vertical, 8)
                .background(isSelected ? Color.blue : Color.secondary.opacity(0.08))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
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
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(isOn ? color : color.opacity(0.12))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}
