import LocalAuthentication
import Security
import SwiftUI

final class Ticket {
    static let shared = Ticket()

    weak var vm: ChatViewModel?
    var creator = ""
    var expiration = Date(timeIntervalSince1970: 0)
    private var storedTicket: String?
    var ticket: String? {
        get { Date() >= expiration ? nil : storedTicket }
        set { storedTicket = newValue }
    }

    private init() {}

    func open(errMsg: Binding<String>, showOk: Binding<Bool>) async {
        guard expiration == Date(timeIntervalSince1970: 0) else { return }

        var existenceQuery: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrDescription: "Ticket",
        ]
        guard SecItemCopyMatching(existenceQuery as CFDictionary, nil) != errSecItemNotFound else {
            await MainActor.run {
                errMsg.wrappedValue = "No previous Ticket found. Will acquire on sign in."
                showOk.wrappedValue = true
            }
            return
        }

        let authContext = LAContext()
#if targetEnvironment(simulator)
        guard (try? await authContext.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: "to allow simulator to access Keychain"
        )) == true else {
            await MainActor.run { errMsg.wrappedValue = "Open Keychain failed" }
            return
        }
#endif
        existenceQuery = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrDescription: "Ticket",
            kSecReturnData: true,
            kSecReturnAttributes: true,
            kSecUseAuthenticationContext: authContext,
        ]
        var itemRef: AnyObject?
        let status = SecItemCopyMatching(existenceQuery as CFDictionary, &itemRef)
        guard status == errSecSuccess else {
            await MainActor.run {
                errMsg.wrappedValue = "Ticket.open: \(securityMessage(status))"
            }
            return
        }

        let formatter = Self.dateFormatter
        guard let item = itemRef as? NSDictionary,
              let data = item[kSecValueData] as? Data,
              let dateString = item[kSecAttrLabel] as? String,
              let ticketExpiration = formatter.date(from: dateString),
              let ticketCreator = item[kSecAttrCreator] as? String,
              let value = String(data: data, encoding: .utf8) else {
            await MainActor.run {
                errMsg.wrappedValue = "Ticket found but invalid; deleting it from Keychain."
            }
            await delete(errMsg: errMsg)
            return
        }

        creator = ticketCreator
        await MainActor.run {
            if Date() >= ticketExpiration {
                errMsg.wrappedValue = "Ticket from last session expired. "
                    + "Will re-acquire on sign in."
            } else {
                ticket = value
                expiration = ticketExpiration
                errMsg.wrappedValue = "Ticket available from last session."
            }
            showOk.wrappedValue = true
        }
    }

    func save(errMsg: Binding<String>, showOk: Binding<Bool>) async {
        guard let data = ticket?.data(using: .utf8) else { return }
        var item: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrDescription: "Ticket",
        ]
        let existingStatus = SecItemCopyMatching(item as CFDictionary, nil)
        let authContext = LAContext()
#if targetEnvironment(simulator)
        guard (try? await authContext.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: "to allow simulator to access Keychain"
        )) == true else {
            await MainActor.run { errMsg.wrappedValue = "Save Keychain failed" }
            return
        }
#endif
        let dateString = Self.dateFormatter.string(from: expiration)
        let status: OSStatus
        if existingStatus == errSecSuccess {
            item[kSecUseAuthenticationContext] = authContext
            status = SecItemUpdate(item as CFDictionary, [
                kSecValueData: data,
                kSecAttrLabel: dateString,
                kSecAttrCreator: creator,
            ] as CFDictionary)
        } else if existingStatus == errSecItemNotFound {
            guard let access = SecAccessControlCreateWithFlags(
                nil,
                kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
                .userPresence,
                nil
            ) else {
                await MainActor.run { errMsg.wrappedValue = "Ticket save access control failed" }
                return
            }
            item.merge([
                kSecValueData: data,
                kSecAttrLabel: dateString,
                kSecAttrCreator: creator,
                kSecAttrAccessControl: access,
                kSecUseAuthenticationContext: authContext,
            ]) { _, new in new }
            status = SecItemAdd(item as CFDictionary, nil)
        } else {
            status = existingStatus
        }

        await MainActor.run {
            if status == errSecSuccess {
                errMsg.wrappedValue = "Ticket saved."
                showOk.wrappedValue = true
            } else {
                errMsg.wrappedValue = securityMessage(status)
                    + "\nThe ticket works until this app exits."
            }
        }
    }

    func delete(errMsg: Binding<String>) async {
        let status = SecItemDelete([
            kSecClass: kSecClassGenericPassword,
            kSecAttrDescription: "Ticket",
        ] as CFDictionary)
        storedTicket = nil
        expiration = Date(timeIntervalSince1970: 0)
        guard status != errSecSuccess, status != errSecItemNotFound else { return }
        await MainActor.run {
            errMsg.wrappedValue += "\nTicket.delete: \(securityMessage(status))"
        }
    }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss '+'SSSS"
        return formatter
    }()
}

private func securityMessage(_ status: OSStatus) -> String {
    SecCopyErrorMessageString(status, nil) as String? ?? "Keychain error \(status)"
}
