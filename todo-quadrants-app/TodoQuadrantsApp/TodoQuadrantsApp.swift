import SwiftData
import SwiftUI

@main
struct TodoQuadrantsApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(modelContainer)
    }

    private var modelContainer: ModelContainer {
        do {
            let schema = Schema([TodoItem.self])
            let configuration = ModelConfiguration(
                schema: schema,
                isStoredInMemoryOnly: false,
                cloudKitDatabase: .private(AppConstants.cloudKitContainerIdentifier)
            )
            return try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Unable to create model container: \(error)")
        }
    }
}
