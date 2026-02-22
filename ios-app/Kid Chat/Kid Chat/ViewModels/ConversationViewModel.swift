//
//  ConversationViewModel.swift
//  Kid Chat
//
//  Conversation state and status text for the chat UI. State is owned by ChatViewModel;
//  this file defines the enum and a shared status string for the view layer.
//

import Foundation
import SwiftUI

// MARK: - Conversation state

/// The four states the chat can be in. The UI uses this to show the right feedback
/// (e.g. "Listening...", thinking dots, or "Talking..."). Single source of truth: ChatViewModel.conversationState.
enum ConversationState {
    /// Ready for input; no mic, no pending reply, no TTS playing.
    case idle
    /// Microphone is recording; user is speaking.
    case listening
    /// Waiting for the backend to respond (or for the short "thinking" delay).
    case thinking
    /// The assistant reply is being read aloud (text-to-speech).
    case speaking

    /// Status string for the header and accessibility. Use when displaying state to the user.
    static func statusText(for state: ConversationState) -> String {
        switch state {
        case .idle: return "Ready to chat!"
        case .listening: return "Listening..."
        case .thinking: return "Thinking..."
        case .speaking: return "Talking..."
        }
    }
}
