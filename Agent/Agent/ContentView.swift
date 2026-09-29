import SwiftUI

enum GameChoice: String, CaseIterable, Identifiable {
    case city = "City"
    case landmark = "Landmark"
    var id: Self { self }
    var rules: String {
        switch self {
        case .city:
            return "We are playing Guess the City. Choose one mystery city now and keep that same city fixed until I guess correctly or give up. Never reveal its name before the round ends. Ask if I am ready, then give 2 or 3 hints at a time and evaluate each guess. Your visible answer must work whether or not you expose reasoning. When I guess correctly, congratulate me, state the city's decimal latitude and longitude, and ask whether I want another round. Only choose a new city after I agree to another round."
        case .landmark:
            return "We are playing Guess the Landmark. Choose one mystery landmark now and keep that same landmark fixed until I guess correctly or give up. Never reveal its name before the round ends. Ask if I am ready, then give 2 or 3 architectural, historical, or geographic hints at a time and evaluate each guess. Your visible answer must work whether or not you expose reasoning. When I guess correctly, congratulate me, state the landmark's city, country, decimal latitude and longitude, and ask whether I want another round. Only choose a new landmark after I agree to another round."
        }
    }
}

enum RequestPhase: Equatable { case idle, initializing, sending, clearing }

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var systemPrompt = ""
    @Published var userPrompt = ""
    @Published var conversation: [Chat] = []
    @Published var errMsg = ""
    @Published var phase = RequestPhase.idle
    @Published var game = GameChoice.city
    let rein = Rein()
    private var initialized = false

    var isBusy: Bool { phase != .idle }
    var canSend: Bool {
        !isBusy && (!systemPrompt.trimmed.isEmpty || !userPrompt.trimmed.isEmpty)
    }

    func startGame() async {
        guard !initialized, phase == .idle else { return }
        initialized = true
        phase = .initializing
        let success = await submit([Message(role: "system", content: game.rules)])
        phase = .idle
        if !success { initialized = false }
    }

    func send() async {
        guard canSend else { return }
        let submittedSystem = systemPrompt.trimmed
        let submittedUser = userPrompt.trimmed
        var messages: [Message] = []
        if !submittedSystem.isEmpty { messages.append(Message(role: "system", content: submittedSystem)) }
        if !submittedUser.isEmpty { messages.append(Message(role: "user", content: submittedUser)) }

        phase = .sending
        if await submit(messages) {
            systemPrompt = ""
            userPrompt = ""
        }
        phase = .idle
    }

    func clear() async {
        guard phase == .idle else { return }
        phase = .clearing
        if await rein.llmClear(errMsg: errMsgBinding) {
            conversation = []
            systemPrompt = ""
            userPrompt = ""
            initialized = false
        }
        phase = .idle
    }

    func selectGame(_ selection: GameChoice) async {
        guard selection != game, phase == .idle else { return }
        phase = .clearing
        guard await rein.llmClear(errMsg: errMsgBinding) else {
            phase = .idle
            return
        }
        game = selection
        conversation = []
        systemPrompt = ""
        userPrompt = ""
        initialized = false
        phase = .idle
        await startGame()
    }

    private func submit(_ messages: [Message]) async -> Bool {
        for message in messages {
            conversation.append(Chat(role: message.role, content: message.content ?? ""))
        }
        conversation.append(Chat(role: "assistant", content: ""))
        let index = conversation.count - 1
        let completionBinding = Binding<Chat>(
            get: { self.conversation[index] },
            set: { self.conversation[index] = $0 }
        )
        return await rein.llmChat(
            messages: messages,
            completion: completionBinding,
            errMsg: errMsgBinding
        )
    }

    private var errMsgBinding: Binding<String> {
        Binding(
            get: { self.errMsg },
            set: { self.errMsg = $0 }
        )
    }
}

struct ContentView: View {
    @StateObject private var vm = ChatViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("Game", selection: Binding(
                    get: { vm.game },
                    set: { choice in Task { await vm.selectGame(choice) } }
                )) {
                    ForEach(GameChoice.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .disabled(vm.isBusy)
                .padding()

                conversationTimeline

                VStack(spacing: 8) {
                    TextField("System prompt (optional)", text: $vm.systemPrompt, axis: .vertical)
                        .lineLimit(1...3)
                        .promptField()

                    HStack(alignment: .bottom, spacing: 10) {
                        TextField("Your guess or message", text: $vm.userPrompt, axis: .vertical)
                            .lineLimit(1...4)
                            .promptField()
                        Button { Task { await vm.send() } } label: {
                            ZStack {
                                Circle()
                                    .fill(vm.canSend ? Color(red: 0, green: 0.153, blue: 0.298) : .gray.opacity(0.45))
                                    .frame(width: 52, height: 52)
                                if vm.phase == .sending || vm.phase == .initializing {
                                    ProgressView().tint(.white)
                                } else {
                                    Image(systemName: "paperplane.fill")
                                        .foregroundStyle(vm.canSend ? Color(red: 1, green: 0.797, blue: 0.02) : .white)
                                }
                            }
                        }
                        .disabled(!vm.canSend)
                        .accessibilityLabel("Send")
                    }

                    Button(role: .destructive) { Task { await vm.clear() } } label: {
                        if vm.phase == .clearing {
                            ProgressView()
                        } else {
                            Label("Clear conversation", systemImage: "trash")
                        }
                    }
                    .disabled(vm.isBusy)
                }
                .disabled(vm.isBusy)
                .padding(.horizontal)
                .padding(.bottom, 12)
            }
            .background(Color(uiColor: .systemGray6))
            .navigationTitle("Where in the World?")
            .navigationBarTitleDisplayMode(.inline)
            .task { await vm.startGame() }
            .alert("LLM Error", isPresented: Binding(
                get: { !vm.errMsg.isEmpty },
                set: { if !$0 { vm.errMsg = "" } }
            )) {
                Button("OK") { vm.errMsg = "" }
            } message: {
                Text(vm.errMsg)
            }
        }
    }

    private var conversationTimeline: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    ForEach(vm.conversation) { ChatBubble(chat: $0).id($0.id) }
                }
                .padding(12)
            }
            .frame(maxHeight: .infinity)
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: vm.conversation.count) { _ in
                if let last = vm.conversation.last {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }
}

struct ChatBubble: View {
    let chat: Chat
    var body: some View {
        HStack {
            if chat.role == "user" { Spacer(minLength: 44) }
            VStack(alignment: .leading, spacing: 3) {
                Text(chat.role.components(separatedBy: " ").first?.capitalized ?? chat.role)
                    .font(.caption).foregroundStyle(.secondary)
                Text(chat.content.isEmpty ? "…" : chat.content).font(.system(size: 17))
            }
            .padding(12)
            .background(
                chat.role == "user" ? Color(red: 1, green: 0.797, blue: 0.02) :
                    chat.role == "system" ? Color.blue.opacity(0.12) : .white,
                in: RoundedRectangle(cornerRadius: 16)
            )
            if chat.role != "user" { Spacer(minLength: 44) }
        }
    }
}

private extension View {
    func promptField() -> some View {
        textFieldStyle(.plain)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(.white, in: RoundedRectangle(cornerRadius: 16))
    }
}
private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
struct ContentView_Previews: PreviewProvider {
    static var previews: some View { ContentView() }
}
