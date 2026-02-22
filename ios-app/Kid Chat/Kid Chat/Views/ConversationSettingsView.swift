//
//  ConversationSettingsView.swift
//  Kid Chat
//
//  Sheet presented from the conversation page: agent voice, mute, and background.
//

import AVFoundation
import SwiftUI

struct ConversationSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var settings: ConversationSettings

    /// English system TTS voices for the picker (sorted by name).
    private static var englishVoices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix("en") }
            .sorted { ($0.name ?? "") < ($1.name ?? "") }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Agent voice") {
                    Picker("Voice", selection: Binding(
                        get: { settings.selectedVoiceIdentifier ?? "" },
                        set: { settings.selectedVoiceIdentifier = $0.isEmpty ? nil : $0 }
                    )) {
                        Text("Default").tag("")
                        ForEach(Self.englishVoices, id: \.identifier) { voice in
                            Text(voice.name ?? voice.identifier).tag(voice.identifier)
                        }
                    }
                    .pickerStyle(.navigationLink)
                }

                Section("Sound") {
                    Toggle("Mute agent voice", isOn: $settings.isAgentMuted)
                }

                Section("Background") {
                    Picker("Conversation background", selection: $settings.backgroundStyle) {
                        ForEach(ConversationBackground.allCases) { style in
                            Text(style.displayName).tag(style)
                        }
                    }
                    .pickerStyle(.navigationLink)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    ConversationSettingsView(settings: ConversationSettings())
}
