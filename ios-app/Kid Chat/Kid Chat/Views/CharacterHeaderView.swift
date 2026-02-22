//
//  CharacterHeaderView.swift
//  Kid Chat
//
//  Reusable header with large emoji avatar, character name, and status text.
//  When idle, avatar gently scales 1.0 ↔ 1.05 (~2s, repeats); animation stops when state changes.
//  Avatar shows the active child profile (or default Astro Buddy); tapping it opens the profile picker.
//

import SwiftUI

// MARK: - Character header

/// A centered header showing an avatar, character name, and status. State comes from ChatViewModel (single source of truth).
/// Avatar and name come from the active child profile (ProfileManager); tap avatar to switch profiles.
struct CharacterHeaderView: View {
    @EnvironmentObject private var profileManager: ProfileManager
    /// Current conversation state (idle / listening / thinking / speaking).
    var conversationState: ConversationState
    /// Status string to display (e.g. "Ready to chat!", "Thinking...").
    var statusText: String
    /// Called when the user taps the avatar; ContentView uses this to present the profile picker sheet.
    var onAvatarTap: () -> Void = {}
    /// When provided, used for the header background; nil = KidTheme gradient.
    var backgroundGradient: LinearGradient?

    /// Emoji for avatar: active profile's or default Astro Buddy.
    private var avatarEmoji: String {
        profileManager.activeProfile?.avatar ?? "🤖"
    }
    /// Name below avatar: active profile's name or default character name.
    private var characterName: String {
        profileManager.activeProfile?.name ?? "Astro Buddy"
    }

    /// Avatar size: large and friendly for kids.
    private let avatarFontSize: CGFloat = 65
    /// Circle size for the avatar background (slightly larger than the emoji).
    private let avatarCircleSize: CGFloat = 88

    var body: some View {
        VStack(spacing: 10) {
            // Large emoji avatar; tap to open profile picker
            Button(action: onAvatarTap) {
                avatarView
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(characterName) avatar")
            .accessibilityHint("Opens profile picker to switch child")

            // Character name: rounded, bold, friendly
            Text(characterName)
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI)

            // Status: when thinking, show animated dots; otherwise show status text
            Group {
                if conversationState == .thinking {
                    ThinkingDotsView()
                } else {
                    Text(statusText)
                        .font(.system(size: 16, weight: .medium, design: .rounded))
                        .foregroundStyle(statusColor)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(statusText)
            .accessibilityHint("Updates frequently")
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(
            backgroundGradient ?? LinearGradient(
                colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )
        )
        .animation(.easeInOut(duration: 0.3), value: conversationState)
    }

    // MARK: - Avatar (emoji + circle + shadow; idle = gentle breathing scale)

    private var avatarView: some View {
        Group {
            if conversationState == .idle {
                TimelineView(.animation(minimumInterval: 0.033)) { context in
                    let t = context.date.timeIntervalSinceReferenceDate
                    let scale = 1.0 + 0.025 * (1 + cos(.pi * t))
                    avatarBody.scaleEffect(scale)
                }
            } else {
                avatarBody
                    .scaleEffect(1.04)
                    .animation(.easeInOut(duration: 0.3), value: conversationState)
            }
        }
    }

    /// Avatar content without scale (used by idle animation and non-idle state).
    private var avatarBody: some View {
        Text(avatarEmoji)
            .font(.system(size: avatarFontSize))
            .frame(width: avatarCircleSize, height: avatarCircleSize)
            .background(Circle().fill(Color.white.opacity(0.9)))
            .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 4)
    }

    /// Status text color by state: idle = gray, listening = red, thinking = orange, speaking = purple.
    private var statusColor: Color {
        switch conversationState {
        case .idle: return .gray
        case .listening: return .red
        case .thinking: return .orange
        case .speaking: return Color(red: 0.6, green: 0.4, blue: 0.9) // purple
        }
    }
}

// MARK: - Preview

#Preview {
    CharacterHeaderView(conversationState: .idle, statusText: ConversationState.statusText(for: .idle), backgroundGradient: nil)
        .environmentObject(ProfileManager())
        .padding()
}
