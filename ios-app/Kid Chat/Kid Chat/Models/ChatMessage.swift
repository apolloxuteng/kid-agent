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
/// - imageData: Optional image attachment (e.g. from Pixabay "show me a picture"); decode from backend base64.
/// - imageMediaType: e.g. "image/jpeg" or "image/webp"; used when imageData is non-nil.
struct ChatMessage: Identifiable {
    let id: UUID
    let text: String
    let isUser: Bool
    let imageData: Data?
    let imageMediaType: String?

    init(id: UUID, text: String, isUser: Bool, imageData: Data? = nil, imageMediaType: String? = nil) {
        self.id = id
        self.text = text
        self.isUser = isUser
        self.imageData = imageData
        self.imageMediaType = imageMediaType
    }
}
