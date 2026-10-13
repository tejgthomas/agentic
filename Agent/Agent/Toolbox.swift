import Foundation

struct OpenAIToolSchema: Codable {
    let type: String = "function"
    let function: OpenAISchemaFunction

    enum CodingKeys: String, CodingKey {
        case type = "type"
        case function = "function"
    }
}

struct OpenAISchemaFunction: Codable {
    let name: String
    let description: String
    let parameters: OpenAIFunctionParams?
}

struct OpenAIFunctionParams: Codable {
    let type: String
    let properties: [String: OpenAIParamProp]?
    let required: [String]?
}

struct OpenAIParamProp: Codable {
    let type: String
    let description: String
    let enum_: [String]?
}

private let Json = JSONDecoder()
fileprivate func jsonToSchema(_ tool: String) -> OpenAIToolSchema {
    guard let url = Bundle.main.url(forResource: tool, withExtension: "json"),
          let data = try? Data(contentsOf: url) else {
        fatalError("Failed to find \(tool).json in bundle")
    }
    do {
        return try Json.decode(OpenAIToolSchema.self, from: data)
    } catch {
        fatalError("Failed to decode \(tool).json: \(error)")
    }
}

func getLocAuth(_ argv: [String]) async -> String {
    guard let presentedTicket = argv.first,
          Ticket.shared.ticket == presentedTicket else {
        return "401 Unauthorized. Ask the user if they want to try again. "
            + "If so, you **MUST** call the get_auth tool again to get a fresh new ticket "
            + "and retry the operation. DO NOT reuse any ticket in context/history that "
            + "came before this message."
    }
    let location = LocManagerViewModel.shared.location
    return "latitude: \(location.lat), longitude: \(location.lon)"
}

func getAuth(_ argv: [String]) async -> String {
    while true {
        if let ticket = Ticket.shared.ticket {
            return "Authorization ticket is: \(ticket)"
        }
        guard let vm = Ticket.shared.vm else {
            return "401 Unauthorized. Complete the prompt by informing user that task "
                + "cannot be completed due to failed authorization."
        }
        await withCheckedContinuation { continuation in
            Task { @MainActor in
                vm.signinCompletion = {
                    continuation.resume()
                }
                vm.getSignedin = true
            }
        }
        if Ticket.shared.ticket == nil {
            return "401 Unauthorized. Complete the prompt by informing user that task "
                + "cannot be completed due to failed authorization."
        }
    }
}

typealias ToolFunction = ([String]) async -> String

struct Tool {
    let schema: OpenAIToolSchema
    let function: ToolFunction
}

struct Toolbox {
    let tools: [String: Tool]

    init() {
        self.tools = [
            "get_auth": Tool(schema: jsonToSchema("get_auth"), function: getAuth),
            "get_loc_auth": Tool(schema: jsonToSchema("get_loc_auth"), function: getLocAuth),
        ]
    }

    func schemas() -> [OpenAIToolSchema] {
        tools.values.map { $0.schema }
    }

    func invoke(function: OpenAIFunction) async -> String? {
        guard let name = function.name, let tool = tools[name] else { return nil }
        guard let argsJson = function.arguments,
              let argsData = argsJson.data(using: .utf8),
              let args = try? JSONSerialization.jsonObject(with: argsData) as? [String: Any] else {
            return "bad tool arguments JSON"
        }

        let argv: [String] = (tool.schema.function.parameters?.required ?? []).map { label in
            switch args[label] {
            case let value as String: return value
            case let value?: return String(describing: value)
            default: return ""
            }
        }
        return await tool.function(argv)
    }
}
