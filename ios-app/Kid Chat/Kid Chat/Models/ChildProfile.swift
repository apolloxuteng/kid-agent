//
//  ChildProfile.swift
//  Kid Chat
//
//  Data model for a single child profile. Used by ProfileManager and persisted
//  to UserDefaults so we can support multiple kids and switch between them.
//

import Foundation

// MARK: - Child profile model

/// Represents one child's profile: name, age, interests, and a fun emoji avatar.
/// Conforms to Identifiable so SwiftUI can use it in ForEach, and Codable for JSON persistence.
struct ChildProfile: Identifiable, Codable {

    /// Unique id; we use this when switching profiles and in the profile list.
    var id: UUID

    /// Display name (e.g. "Sam", "Alex").
    var name: String

    /// Age in years; useful for age-appropriate content later.
    var age: Int

    /// Things the child likes; can be used to personalize conversations.
    var interests: [String]

    /// Single emoji used as the profile avatar (e.g. "🌟", "🦊").
    var avatar: String

    /// Creates a new profile with the given fields. Use this when adding a profile from the UI.
    init(id: UUID = UUID(), name: String, age: Int, interests: [String], avatar: String) {
        self.id = id
        self.name = name
        self.age = age
        self.interests = interests
        self.avatar = avatar
    }
}
