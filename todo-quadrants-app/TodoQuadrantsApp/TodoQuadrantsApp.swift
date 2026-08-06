import SwiftData
import SwiftUI
#if os(macOS)
import Security
#endif

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
            let configuration: ModelConfiguration

            if hasCloudKitEntitlement {
                configuration = ModelConfiguration(
                    schema: schema,
                    isStoredInMemoryOnly: false,
                    cloudKitDatabase: .private(AppConstants.cloudKitContainerIdentifier)
                )
            } else {
                configuration = ModelConfiguration(
                    schema: schema,
                    isStoredInMemoryOnly: false
                )
            }

            return try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Unable to create model container: \(error)")
        }
    }

    private var hasCloudKitEntitlement: Bool {
        #if os(macOS)
        guard
            let task = SecTaskCreateFromSelf(nil),
            let value = SecTaskCopyValueForEntitlement(
                task,
                "com.apple.developer.icloud-services" as CFString,
                nil
            )
        else {
            return false
        }

        if let services = value as? [String] {
            return services.contains("CloudKit")
        }

        if let service = value as? String {
            return service == "CloudKit"
        }

        return false
        #else
        #if DEBUG
        return false
        #else
        return true
        #endif
        #endif
    }
}
