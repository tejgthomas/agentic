import Foundation

struct Chat: Identifiable, Hashable {
    let id = UUID()
    var role = "user"
    var content = ""
    var timestamp = Date()
}
