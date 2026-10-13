import GoogleSignIn
import SwiftUI

@main
struct AgentApp: App {
    @StateObject private var vm = ChatViewModel()

    init() {
        LocManager.shared.startUpdates()
    }

    var body: some Scene {
        WindowGroup {
            ContentView(vm: vm)
                .onOpenURL { url in
                    GIDSignIn.sharedInstance.handle(url)
                }
                .task {
                    Ticket.shared.vm = vm
                    await Ticket.shared.open(errMsg: $vm.errMsg, showOk: $vm.showOk)
                }
        }
    }
}
