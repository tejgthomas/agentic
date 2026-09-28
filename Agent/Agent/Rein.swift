import Foundation
import SwiftUI

private let harness = "https://34.56.51.226"
private let api = "/llmchat"
private let appID = Bundle.main.bundleIdentifier ?? "edu.umich.tejg.agent"
private let model = "gemma4:e4b"
private let showThinking = true

struct Message: Codable {
    var role = "user"
    var content: String?
}

struct OpenAIRequest: Codable {
    var appID: String
    var model: String
    var messages: [Message]
    var stream = true
}

struct Delta: Codable {
    var content: String?
    var reasoning: String?
    var reasoning_content: String?
}

struct Choice: Codable {
    var delta: Delta
    var finish_reason: String?
}

struct OpenAIResponse: Codable {
    var model: String?
    var choices: [Choice]
    var created: Int?
}

enum SseEvent {
    case error
    case message
    case unknown
}

final class Rein {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var isThinking = false

    @MainActor
    func llmChat(
        messages: [Message],
        completion: Binding<Chat>,
        errMsg: Binding<String>
    ) async {
        isThinking = false
        let requestBody = OpenAIRequest(appID: appID, model: model, messages: messages)
        let request: URLRequest

        do {
            request = try prepareRequest(body: requestBody)
        } catch {
            errMsg.wrappedValue = "Prepare request failed \(error)"
            return
        }

        do {
            let (bytes, response) = try await URLSession.shared.bytes(for: request)
            guard let http = response as? HTTPURLResponse else {
                errMsg.wrappedValue = "Harness returned a non-HTTP response."
                return
            }
            guard http.statusCode == 200 else {
                errMsg.wrappedValue = "Harness returned HTTP \(http.statusCode)."
                return
            }
            try await processSse(bytes: bytes, completion: completion, errMsg: errMsg)
        } catch {
            errMsg.wrappedValue = "Connect to harness failed \(error)"
        }
    }

    private func prepareRequest(body: OpenAIRequest) throws -> URLRequest {
        guard let url = URL(string: "\(harness)\(api)") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.httpBody = try encoder.encode(body)
        return request
    }

    @MainActor
    private func processSse(
        bytes: URLSession.AsyncBytes,
        completion: Binding<Chat>,
        errMsg: Binding<String>
    ) async throws {
        var event = SseEvent.message

        for try await line in bytes.lines {
            if line.isEmpty {
                event = .message
                continue
            }

            let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2 else {
                continue
            }

            let tag = String(parts[0])
            let value = parts[1].trimmingCharacters(in: .whitespaces)

            if tag == "event" {
                switch value.lowercased() {
                case "error":
                    event = .error
                case "message":
                    event = .message
                default:
                    event = .unknown
                }
                continue
            }

            guard tag == "data", !value.isEmpty, value != "[DONE]" else {
                continue
            }

            switch event {
            case .message:
                try handleMessageData(value, completion: completion, errMsg: errMsg)
            case .error:
                let message = "**SSE Error Event** \(value)"
                completion.wrappedValue.content = message
                errMsg.wrappedValue = value
            case .unknown:
                errMsg.wrappedValue += "\n\nUnknown SSE event: \(value)"
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
        guard let choice = response.choices.first else {
            return
        }

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

        guard showThinking else {
            return ""
        }

        let reason = [delta.reasoning_content, delta.reasoning]
            .compactMap { $0 }
            .first { !$0.isEmpty }

        guard let reason else {
            return ""
        }

        let result = isThinking ? reason : "<think>\n\(reason)"
        isThinking = true
        return result
    }
}
