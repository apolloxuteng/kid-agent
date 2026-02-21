//
//  ChatMessage.swift
//  Kid Chat
//
//  Data model for a single chat message (user or AI).
//

import Foundation

/// A single message in the chat.
/// - id: Unique identifier (used by SwiftUI list and scroll targeting).
/// - text: The message content.
/// - isUser: true = sent by the user (right side), false = from AI (left side).
struct ChatMessage: Identifiable {
    let id: UUID
    let text: String
    let isUser: Bool
}
