import SwiftUI

final class ChatViewModel: ObservableObject {
    @Published var message = "howdy?"
    @Published var instruction = "Type a message..."
    @Published var conversation: [Chat] = []
    @Published var errMsg = ""
    @Published var isSending = false
    @Published var showOk = false
    @Published var getSignedin = false
    var signinCompletion: (() -> Void)?
    let rein = Rein()
}

struct ContentView: View {
    @ObservedObject var vm: ChatViewModel

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 10) {
                            ForEach($vm.conversation) { $chat in
                                ChatBubble(chat: chat)
                                    .id(chat.id)
                            }
                        }
                        .padding(12)
                    }
                    .onChange(of: vm.conversation.map(\.content)) { _ in
                        if let last = vm.conversation.last {
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }

                HStack(spacing: 12) {
                    TextField(vm.instruction, text: $vm.message, axis: .vertical)
                        .lineLimit(1...6)
                        .textFieldStyle(.plain)
                        .font(.system(size: 18))
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(.white, in: RoundedRectangle(cornerRadius: 22))

                    SubmitButton(vm: vm)
                }
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, 20)
                .background(Color(uiColor: .systemGray6))
            }
            .background(Color(uiColor: .systemGray6))
            .navigationTitle("llmHITL")
            .navigationBarTitleDisplayMode(.inline)
            .alert(vm.showOk ? "Advisory" : "LLM Error", isPresented: Binding(
                get: { !vm.errMsg.isEmpty },
                set: {
                    if !$0 {
                        vm.errMsg = ""
                        vm.showOk = false
                    }
                }
            )) {
                Button("OK") {
                    vm.errMsg = ""
                    vm.showOk = false
                }
            } message: {
                Text(vm.errMsg)
            }
            .sheet(isPresented: $vm.getSignedin) {
                SigninView(vm: vm, isPresenting: $vm.getSignedin)
                    .presentationDetents([.fraction(0.25)])
                    .presentationDragIndicator(.hidden)
                    .interactiveDismissDisabled()
            }
        }
    }
}

struct ChatBubble: View {
    let chat: Chat

    var body: some View {
        HStack {
            if chat.role == "user" {
                Spacer(minLength: 44)
            }

            Text(chat.content)
                .font(.system(size: 18))
                .foregroundStyle(chat.role == "user" ? Color(red: 0, green: 0.153, blue: 0.298) : .primary)
                .padding(14)
                .background(
                    chat.role == "user" ? Color(red: 1, green: 0.797, blue: 0.02) : .white,
                    in: RoundedRectangle(cornerRadius: 18)
                )

            if chat.role != "user" {
                Spacer(minLength: 44)
            }
        }
    }
}

struct SubmitButton: View {
    @ObservedObject var vm: ChatViewModel

    var body: some View {
        Button {
            submit()
        } label: {
            ZStack {
                Circle()
                    .fill(vm.message.isEmpty ? Color(red: 0, green: 0.153, blue: 0.298).opacity(0.45) : Color(red: 0, green: 0.153, blue: 0.298))
                    .frame(width: 55, height: 55)

                if vm.isSending {
                    ProgressView()
                        .tint(.white)
                } else {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(vm.message.isEmpty ? .gray : Color(red: 1, green: 0.797, blue: 0.02))
                }
            }
        }
        .disabled(vm.message.isEmpty || vm.isSending)
    }

    private func submit() {
        guard !vm.message.isEmpty, !vm.isSending else {
            return
        }

        vm.isSending = true

        let chat = Chat(role: "user", content: vm.message)
        vm.conversation.append(chat)

        let completion = Chat(role: "assistant", content: "", timestamp: Date())
        vm.conversation.append(completion)
        let completionIndex = vm.conversation.count - 1
        let messages = [Message(role: chat.role, content: chat.content)]

        Task {
            await vm.rein.llmTools(
                messages,
                completion: $vm.conversation[completionIndex],
                errMsg: $vm.errMsg
            )
            vm.message = ""
            vm.isSending = false
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView(vm: ChatViewModel())
    }
}
