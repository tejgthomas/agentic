import SwiftUI

@main
struct AgentApp: App {
    init() {
        LocManager.shared.startUpdates()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
