import GoogleSignIn
import GoogleSignInSwift
import SwiftUI

extension GIDSignIn {
    func signInAsync(withPresenting presenting: UIViewController) async -> String? {
        await withCheckedContinuation { continuation in
            signIn(withPresenting: presenting) { result, error in
                if let error {
                    print("Google Sign-In error: \(error.localizedDescription)")
                }
                continuation.resume(returning: result?.user.idToken?.tokenString)
            }
        }
    }

    func restorePreviousSignInAsync() async -> String? {
        await withCheckedContinuation { continuation in
            restorePreviousSignIn { user, error in
                if let error {
                    print("Google restore error: \(error.localizedDescription)")
                }
                continuation.resume(returning: user?.idToken?.tokenString)
            }
        }
    }
}

struct SigninView: View {
    @ObservedObject var vm: ChatViewModel
    @Binding var isPresenting: Bool
    private let signinClient = GIDSignIn.sharedInstance
    @State private var isRefreshing = true

    var body: some View {
        VStack {
            Spacer()
            if isRefreshing {
                VStack(spacing: 16) {
                    Text("Refreshing credentials...")
                    ProgressView().controlSize(.large)
                }
            } else {
                GoogleSignInButton {
                    Task { await signIn() }
                }
                .frame(width: 180, height: 50)
            }
            Spacer()
        }
        .task { await restoreOrRefresh() }
        .onDisappear {
            let completion = vm.signinCompletion
            vm.signinCompletion = nil
            completion?()
        }
    }

    @MainActor
    private func restoreOrRefresh() async {
        if let token = signinClient.currentUser?.idToken?.tokenString {
            await getTicket(token)
            isPresenting = false
            return
        }
        if let token = await signinClient.restorePreviousSignInAsync() {
            await getTicket(token)
            isPresenting = false
        } else {
            isRefreshing = false
        }
    }

    @MainActor
    private func signIn() async {
        guard let root = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?
            .keyWindow?.rootViewController else {
            vm.errMsg = "Unable to present Google Sign-In."
            isPresenting = false
            return
        }
        if let token = await signinClient.signInAsync(withPresenting: root) {
            await getTicket(token)
        } else {
            vm.errMsg = "Failed Google Sign-In. Please try again."
        }
        isPresenting = false
    }

    @MainActor
    private func getTicket(_ token: String?) async {
        guard await vm.rein.addAgent(token, errMsg: $vm.errMsg) != nil else {
            if vm.errMsg.isEmpty {
                vm.errMsg = "harnessd cannot add user. Please try again."
            }
            return
        }
        await Ticket.shared.save(errMsg: $vm.errMsg, showOk: $vm.showOk)
        if vm.errMsg.isEmpty {
            vm.errMsg = "Ticket refreshed."
            vm.showOk = true
        }
    }
}
