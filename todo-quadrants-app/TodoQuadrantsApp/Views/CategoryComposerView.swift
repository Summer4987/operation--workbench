import SwiftUI

struct CategoryComposerView: View {
    let onAdd: (_ title: String, _ category: TodoCategory, _ isImportant: Bool, _ isUrgent: Bool) -> Void

    @State private var drafts: [TodoCategory: String] = Dictionary(uniqueKeysWithValues: TodoCategory.allCases.map { ($0, "") })
    @State private var isImportant = true
    @State private var isUrgent = true

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("添加待办")
                    .font(.headline)
                Spacer()
                Toggle("重要", isOn: $isImportant)
                    .toggleStyle(.button)
                Toggle("紧急", isOn: $isUrgent)
                    .toggleStyle(.button)
            }

            VStack(spacing: 8) {
                ForEach(TodoCategory.allCases) { category in
                    HStack(spacing: 10) {
                        Text(category.rawValue)
                            .font(.subheadline.weight(.semibold))
                            .frame(width: 76, alignment: .leading)

                        TextField("输入待办", text: binding(for: category))
                            .textFieldStyle(.roundedBorder)
                            .submitLabel(.done)
                            .onSubmit {
                                add(category)
                            }

                        Button {
                            add(category)
                        } label: {
                            Image(systemName: "plus.circle.fill")
                                .font(.title3)
                        }
                        .buttonStyle(.borderless)
                        .disabled(trimmedDraft(for: category).isEmpty)
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

    private func binding(for category: TodoCategory) -> Binding<String> {
        Binding(
            get: { drafts[category, default: ""] },
            set: { drafts[category] = $0 }
        )
    }

    private func trimmedDraft(for category: TodoCategory) -> String {
        drafts[category, default: ""].trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func add(_ category: TodoCategory) {
        let title = trimmedDraft(for: category)
        guard !title.isEmpty else { return }
        onAdd(title, category, isImportant, isUrgent)
        drafts[category] = ""
    }
}
