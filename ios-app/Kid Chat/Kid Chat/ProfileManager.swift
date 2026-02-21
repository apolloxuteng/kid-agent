//
//  ProfileManager.swift
//  Kid Chat
//
//  Manages multiple child profiles and the currently active one. Persists to
//  UserDefaults so profiles survive app restarts. Use as an EnvironmentObject
//  so the whole app can react to profile changes (e.g. reset chat when switching).
//

import Foundation
import SwiftUI

// MARK: - Profile manager

/// ObservableObject that holds the list of profiles and the active profile.
/// Call loadProfiles() once at app launch; use addProfile() and switchProfile(id:) from the UI.
class ProfileManager: ObservableObject {

    /// Maximum number of profiles allowed (add button disabled and addProfile returns false when at limit).
    static let maxProfiles = 5

    // MARK: - Published state

    /// All saved child profiles. Updated when we add a new profile or (in the future) edit/delete.
    @Published var profiles: [ChildProfile] = []

    /// The profile currently "active" — this is whose avatar and context we use in chat.
    /// Nil if there are no profiles yet (user should add one).
    @Published var activeProfile: ChildProfile?

    // MARK: - UserDefaults keys

    /// Key where we store the JSON-encoded array of profiles.
    private let profilesKey = "KidChat.ChildProfiles"
    /// Key where we store the active profile's id (UUID string) so we can restore it on launch.
    private let activeProfileIDKey = "KidChat.ActiveProfileID"

    // MARK: - Initialization and persistence

    init() {
        loadProfiles()
    }

    /// Loads profiles from UserDefaults and restores the active profile by id.
    /// Call this on init; SwiftUI views don't need to call it.
    func loadProfiles() {
        guard let data = UserDefaults.standard.data(forKey: profilesKey) else {
            profiles = []
            activeProfile = nil
            return
        }
        let decoder = JSONDecoder()
        profiles = (try? decoder.decode([ChildProfile].self, from: data)) ?? []
        // Restore active profile by saved id
        if let idString = UserDefaults.standard.string(forKey: activeProfileIDKey),
           let id = UUID(uuidString: idString),
           let match = profiles.first(where: { $0.id == id }) {
            activeProfile = match
        } else {
            // No valid saved active id: use first profile if any
            activeProfile = profiles.first
            if let first = profiles.first {
                UserDefaults.standard.set(first.id.uuidString, forKey: activeProfileIDKey)
            }
        }
    }

    /// Saves the current profiles array to UserDefaults (JSON encoded).
    /// Call this after adding (or in the future, editing/deleting) a profile.
    func saveProfiles() {
        let encoder = JSONEncoder()
        guard let data = try? encoder.encode(profiles) else { return }
        UserDefaults.standard.set(data, forKey: profilesKey)
        // Keep active profile id in sync
        if let active = activeProfile {
            UserDefaults.standard.set(active.id.uuidString, forKey: activeProfileIDKey)
        }
    }

    // MARK: - Actions

    /// Appends a new profile and saves. Optionally makes it the active profile.
    /// - Returns: false if already at max profiles (5); true if the profile was added.
    func addProfile(_ profile: ChildProfile, setActive: Bool = true) -> Bool {
        guard profiles.count < Self.maxProfiles else { return false }
        profiles.append(profile)
        if setActive {
            activeProfile = profile
            UserDefaults.standard.set(profile.id.uuidString, forKey: activeProfileIDKey)
        }
        saveProfiles()
        return true
    }

    /// Switches the active profile to the one with the given id.
    /// Does nothing if no profile has that id. Caller (e.g. ContentView) should reset chat state.
    /// - Parameter id: The UUID of the profile to make active.
    func switchProfile(id: UUID) {
        guard let match = profiles.first(where: { $0.id == id }) else { return }
        activeProfile = match
        UserDefaults.standard.set(match.id.uuidString, forKey: activeProfileIDKey)
        saveProfiles()
    }
}
