//
//  ConversationSettings.swift
//  Kid Chat
//
//  User preferences for the conversation page: agent voice, mute, and background.
//  Persisted in UserDefaults so choices survive app restart.
//

import SwiftUI

// MARK: - App theme (background + accent for buttons)

/// App theme: conversation background gradient and accent gradient for header/secondary buttons.
/// User picks a theme in Settings; it controls both the chat background and the look of Mode/Settings buttons.
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

    /// Background gradient for the conversation area and header.
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

    /// Accent gradient for header buttons (Mode, Settings) and other themed controls. Matches the theme’s palette.
    var accentGradient: LinearGradient {
        switch self {
        case .pastelBlue:
            let start = KidTheme.micIdle
            let end = Color(red: 0.25, green: 0.45, blue: 0.88)
            return LinearGradient(colors: [start, end], startPoint: .topLeading, endPoint: .bottomTrailing)
        case .lavender:
            let start = Color(red: 0.75, green: 0.65, blue: 1.0)
            let end = Color(red: 0.55, green: 0.45, blue: 0.9)
            return LinearGradient(colors: [start, end], startPoint: .topLeading, endPoint: .bottomTrailing)
        case .mint:
            let start = Color(red: 0.45, green: 0.82, blue: 0.65)
            let end = Color(red: 0.35, green: 0.7, blue: 0.55)
            return LinearGradient(colors: [start, end], startPoint: .topLeading, endPoint: .bottomTrailing)
        case .softSunset:
            let start = Color(red: 1.0, green: 0.7, blue: 0.5)
            let end = Color(red: 0.9, green: 0.55, blue: 0.4)
            return LinearGradient(colors: [start, end], startPoint: .topLeading, endPoint: .bottomTrailing)
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

    /// Gradient for the conversation page and header. Derived from selected theme.
    var conversationGradient: LinearGradient {
        backgroundStyle.gradient
    }

    /// Accent gradient for header buttons (Mode, Settings). Derived from selected theme.
    var accentGradient: LinearGradient {
        backgroundStyle.accentGradient
    }

    init() {
        let storedVoice = UserDefaults.standard.string(forKey: StorageKey.selectedVoiceIdentifier)
        self.selectedVoiceIdentifier = storedVoice == "" ? nil : storedVoice
        self.isAgentMuted = UserDefaults.standard.object(forKey: StorageKey.isAgentMuted) as? Bool ?? false
        let raw = UserDefaults.standard.string(forKey: StorageKey.backgroundStyle) ?? ConversationBackground.pastelBlue.rawValue
        self.backgroundStyle = ConversationBackground(rawValue: raw) ?? .pastelBlue
    }
}
