import Foundation
import SwiftUI

private let harness = "https://34.56.51.226"
private let api = "/llmtools"
private let appID = Bundle.main.bundleIdentifier ?? "edu.umich.tejg.agent"
private let toolbox = Toolbox()
private let model = "qwen3.5:9b"
private let showThinking = true

struct OpenAIFunction: Codable {
    let name: String?
    let arguments: String?
}

struct OpenAIToolCall: Codable {
    let id: String
    let type: String = "function"
    let function: OpenAIFunction

    enum CodingKeys: String, CodingKey {
        case id = "id"
        case type = "type"
        case function = "function"
    }
}

struct Message: Encodable {
    let role: String
    let content: String?
    var tool_calls: [OpenAIToolCall]?
    var tool_call_id: String?

    init(
        role: String = "user",
        content: String = "",
        tool_calls: [OpenAIToolCall]? = nil,
        tool_call_id: String? = nil
    ) {
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
    }
}

struct OpenAIRequest: Encodable {
    let appID: String
    var turnID: Int64?
    let model: String
    let max_tokens = 8192
    var messages: [Message]
    var tools: [OpenAIToolSchema]?
    let stream = true

    init(
        appID: String,
        turnID: Int64? = nil,
        model: String,
        messages: [Message],
        tools: [OpenAIToolSchema]? = nil
    ) {
        self.appID = appID
        self.turnID = turnID
        self.model = model
        self.messages = messages
        self.tools = tools
    }
}

struct ToolCallDelta: Decodable {
    let index: Int
    let id: String?
    let function: OpenAIFunction?
}

struct Delta: Decodable {
    let content: String?
    let reasoning: String?
    let reasoning_content: String?
    let tool_calls: [ToolCallDelta]?
}

struct Choice: Decodable {
    let delta: Delta
    let finish_reason: String?
}

struct OpenAIResponse: Decodable {
    let model: String?
    let choices: [Choice]?
    let created: Int?
}

enum SseEvent { case Error, Message, ToolCalls, Unknown }

struct ToolCallsData: Decodable {
    let turnID: Int64
    let calls: [OpenAIToolCall]
}

private struct SseAccumulator {
    let completion: Binding<Chat>
    let errMsg: Binding<String>
    var turnID: Int64? = nil
    var parallelCalls = [OpenAIToolCall]()
}

final class Rein {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var isThinking = false

    func addAgent(_ idToken: String?, errMsg: Binding<String>) async -> String? {
        guard let idToken,
              let clientID = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String,
              !clientID.isEmpty else {
            errMsg.wrappedValue = "Missing Google OAuth client ID. "
                + "Set GOOGLE_CLIENT_ID in the Agent target build settings."
            return nil
        }
        guard let harnessApi = URL(string: "\(harness)/addagent") else {
            errMsg.wrappedValue = "addAgent: Bad URL"
            return nil
        }
        let agentAuth = ["clientID": clientID, "idToken": idToken]
        guard let requestBody = try? JSONSerialization.data(withJSONObject: agentAuth) else {
            errMsg.wrappedValue = "addAgent: JSON serialization failed"
            return nil
        }

        var request = URLRequest(url: harnessApi)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestBody
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                let description = HTTPURLResponse.localizedString(forStatusCode: status)
                errMsg.wrappedValue = "addAgent: \(status) \(description)"
                return nil
            }
            guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let ticket = object["ticket"] as? String,
                  let lifetime = object["lifetime"] as? TimeInterval else {
                errMsg.wrappedValue = "addAgent: Invalid response"
                return nil
            }
            Ticket.shared.ticket = ticket
            Ticket.shared.creator = object["creator"] as? String ?? "Profile NA"
            Ticket.shared.expiration = Date().addingTimeInterval(lifetime - 1)
            return ticket
        } catch {
            errMsg.wrappedValue = "addAgent: POST failed \(error.localizedDescription)"
            return nil
        }
    }

    @MainActor
    func llmTools(
        _ messages: [Message],
        completion: Binding<Chat>,
        errMsg: Binding<String>
    ) async {
        guard let harnessApi = URL(string: "\(harness)\(api)") else {
            errMsg.wrappedValue = "Bad harness URL \(harness)\(api)"
            return
        }

        isThinking = false
        errMsg.wrappedValue = ""
        var openAIRequest = OpenAIRequest(
            appID: appID,
            model: model,
            messages: messages,
            tools: toolbox.schemas()
        )
        var sendNewPrompt = true

        while sendNewPrompt {
            sendNewPrompt = false
            let request: URLRequest
            do {
                request = try prepareRequest(harnessApi, openAIRequest)
            } catch {
                errMsg.wrappedValue = "Prepare request failed \(error)"
                return
            }

            let bytes: URLSession.AsyncBytes
            do {
                bytes = try await postPrompt(request)
            } catch {
                errMsg.wrappedValue = "Connect to harness failed \(error)"
                return
            }

            var acc = SseAccumulator(completion: completion, errMsg: errMsg)
            do {
                try await processSse(bytes, &acc)
            } catch {
                errMsg.wrappedValue = "SSE parsing failed \(error)"
                completion.wrappedValue.content.append("\n\n**\(errMsg.wrappedValue)**\n\n")
                return
            }

            if !acc.parallelCalls.isEmpty {
                guard let turnID = acc.turnID else {
                    errMsg.wrappedValue = "Tool call event missing turnID"
                    completion.wrappedValue.content.append("\n\n**\(errMsg.wrappedValue)**\n\n")
                    return
                }

                var toolResults = [Message]()
                for call in acc.parallelCalls {
                    let result = await toolbox.invoke(function: call.function)
                        ?? "Tool '\(call.function.name ?? "unknown")' does not exist. Complete the prompt without the tool."
                    toolResults.append(Message(
                        role: "tool",
                        content: result,
                        tool_call_id: call.id
                    ))
                }

                openAIRequest.messages = toolResults
                openAIRequest.turnID = turnID
                openAIRequest.tools = nil
                sendNewPrompt = true
            }
        }
    }

    private func prepareRequest(_ url: URL, _ body: OpenAIRequest) throws -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.httpBody = try encoder.encode(body)
        return request
    }

    private func postPrompt(_ request: URLRequest) async throws -> URLSession.AsyncBytes {
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard http.statusCode == 200 else {
            throw URLError(.badServerResponse, userInfo: [
                NSLocalizedDescriptionKey: "Harness returned HTTP \(http.statusCode)."
            ])
        }
        return bytes
    }

    @MainActor
    private func processSse(
        _ bytes: URLSession.AsyncBytes,
        _ acc: inout SseAccumulator
    ) async throws {
        var sseEvent = SseEvent.Message

        for try await line in bytes.lines {
            if line.isEmpty {
                sseEvent = .Message
                continue
            }

            let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2 else { continue }
            let tag = String(parts[0])
            let tagline = parts[1].trimmingCharacters(in: .whitespaces)

            if tag == "event" {
                switch tagline {
                case "error", "Error", "ERROR": sseEvent = .Error
                case "message", "Message", "MESSAGE": sseEvent = .Message
                case "tool_calls", "Tool_calls", "TOOL_CALLS": sseEvent = .ToolCalls
                default: sseEvent = .Unknown
                }
                continue
            }

            guard tag == "data", !tagline.isEmpty, tagline != "[DONE]" else { continue }
            switch sseEvent {
            case .Message:
                try handleMessageData(tagline, completion: acc.completion, errMsg: acc.errMsg)
            case .ToolCalls:
                let event = try decoder.decode(ToolCallsData.self, from: Data(tagline.utf8))
                acc.turnID = event.turnID
                acc.parallelCalls.append(contentsOf: event.calls)
            case .Error:
                let message = "**SSE Error Event** \(tagline)"
                acc.completion.wrappedValue.content = message
                acc.errMsg.wrappedValue = tagline
            case .Unknown:
                acc.errMsg.wrappedValue += "\n\nUnknown SSE event: \(tagline)"
            }
        }
    }

    @MainActor
    private func handleMessageData(
        _ data: String,
        completion: Binding<Chat>,
        errMsg: Binding<String>
    ) throws {
        let response = try decoder.decode(OpenAIResponse.self, from: Data(data.utf8))
        guard let choice = response.choices?.first else { return }

        let token = decoratedContent(choice.delta)
        if !token.isEmpty {
            completion.wrappedValue.content += token
            if let responseModel = response.model {
                completion.wrappedValue.role = "assistant (\(responseModel))"
            }
            if let created = response.created {
                completion.wrappedValue.timestamp = Date(timeIntervalSince1970: TimeInterval(created))
            }
        }

        if choice.finish_reason == "length" || choice.finish_reason == "content_filter" {
            errMsg.wrappedValue = "LLM STREAM CUT OFF!"
        }
    }

    private func decoratedContent(_ delta: Delta) -> String {
        if let content = delta.content, !content.isEmpty {
            let result = isThinking ? "\n</think>\n\n\(content)" : content
            isThinking = false
            return result
        }
        guard showThinking else { return "" }
        let reason = [delta.reasoning_content, delta.reasoning]
            .compactMap { $0 }
            .first { !$0.isEmpty }
        guard let reason else { return "" }
        let result = isThinking ? reason : "<think>\n\(reason)"
        isThinking = true
        return result
    }
}
