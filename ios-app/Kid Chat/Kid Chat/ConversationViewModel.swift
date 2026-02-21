//
//  ConversationViewModel.swift
//  Kid Chat
//
//  Simple conversation state system for the chat UI.
//  Tracks whether we're idle, listening (mic), thinking (waiting for reply), or speaking (TTS).
//  Beginner-friendly: one place for state and status text the view can display.
//

import Foundation
import SwiftUI

// MARK: - Conversation state

/// The four states the chat can be in. The UI uses this to show the right feedback
/// (e.g. "Listening...", thinking dots, or "Talking...").
enum ConversationState {
    /// Ready for input; no mic, no pending reply, no TTS playing.
    case idle
    /// Microphone is recording; user is speaking.
    case listening
    /// Waiting for the backend to respond (or for the short "thinking" delay).
    case thinking
    /// The assistant reply is being read aloud (text-to-speech).
    case speaking
}

// MARK: - Conversation view model

/// Holds the current conversation state and provides a friendly status string for the UI.
/// ContentView observes this with @StateObject so the header and buttons update automatically.
class ConversationViewModel: ObservableObject {

    /// Current state: idle, listening, thinking, or speaking.
    /// When this changes, SwiftUI redraws any view that uses it.
    @Published var state: ConversationState = .idle

    /// A short status string for each state. Use this in the header so the child
    /// (and parent) knows what the app is doing.
    var statusText: String {
        switch state {
        case .idle: return "Ready to chat!"
        case .listening: return "Listening..."
        case .thinking: return "Thinking..."
        case .speaking: return "Talking..."
        }
    }
}
