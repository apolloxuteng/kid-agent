//
//  KidChatApp.swift
//  Kid Chat
//
//  App entry point. Creates the main window with ContentView and injects
//  ProfileManager so the whole app can switch between child profiles.
//

import SwiftUI

@main
struct KidChatApp: App {
    /// Single source of truth for child profiles; created once and passed down.
    @StateObject private var profileManager = ProfileManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(profileManager)
        }
    }
}

