//
//  ConversationSettings.swift
//  Kid Chat
//
//  User preferences for the conversation page: agent voice, mute, and background.
//  Persisted in UserDefaults so choices survive app restart.
//

import SwiftUI

// MARK: - Background style

/// Conversation page background options. Each case provides a LinearGradient.
enum ConversationBackground: String, CaseIterable, Identifiable {
    case pastelBlue = "pastelBlue"
    case lavender = "lavender"
    case mint = "mint"
    case softSunset = "softSunset"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .pastelBlue: return "Pastel blue"
        case .lavender: return "Lavender"
        case .mint: return "Mint"
        case .softSunset: return "Soft sunset"
        }
    }

    var gradient: LinearGradient {
        switch self {
        case .pastelBlue:
            return LinearGradient(
                colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )
        case .lavender:
            let top = Color(red: 0.92, green: 0.88, blue: 1.0)
            let bottom = Color(red: 0.88, green: 0.92, blue: 1.0)
            return LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom)
        case .mint:
            let top = Color(red: 0.85, green: 0.98, blue: 0.92)
            let bottom = Color(red: 0.9, green: 0.98, blue: 0.95)
            return LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom)
        case .softSunset:
            let top = Color(red: 1.0, green: 0.92, blue: 0.88)
            let bottom = Color(red: 0.98, green: 0.9, blue: 0.92)
            return LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom)
        }
    }
}

// MARK: - Settings store

private enum StorageKey {
    static let selectedVoiceIdentifier = "conversationSettings.selectedVoiceIdentifier"
    static let isAgentMuted = "conversationSettings.isAgentMuted"
    static let backgroundStyle = "conversationSettings.backgroundStyle"
}

/// User preferences for the conversation page. Persisted to UserDefaults.
final class ConversationSettings: ObservableObject {
    @Published var selectedVoiceIdentifier: String? {
        didSet {
            if let id = selectedVoiceIdentifier {
                UserDefaults.standard.set(id, forKey: StorageKey.selectedVoiceIdentifier)
            } else {
                UserDefaults.standard.removeObject(forKey: StorageKey.selectedVoiceIdentifier)
            }
        }
    }

    @Published var isAgentMuted: Bool {
        didSet {
            UserDefaults.standard.set(isAgentMuted, forKey: StorageKey.isAgentMuted)
        }
    }

    @Published var backgroundStyle: ConversationBackground {
        didSet {
            UserDefaults.standard.set(backgroundStyle.rawValue, forKey: StorageKey.backgroundStyle)
        }
    }

    /// Gradient for the conversation page and header. Derived from backgroundStyle.
    var conversationGradient: LinearGradient {
        backgroundStyle.gradient
    }

    init() {
        let storedVoice = UserDefaults.standard.string(forKey: StorageKey.selectedVoiceIdentifier)
        self.selectedVoiceIdentifier = storedVoice == "" ? nil : storedVoice
        self.isAgentMuted = UserDefaults.standard.object(forKey: StorageKey.isAgentMuted) as? Bool ?? false
        let raw = UserDefaults.standard.string(forKey: StorageKey.backgroundStyle) ?? ConversationBackground.pastelBlue.rawValue
        self.backgroundStyle = ConversationBackground(rawValue: raw) ?? .pastelBlue
    }
}
