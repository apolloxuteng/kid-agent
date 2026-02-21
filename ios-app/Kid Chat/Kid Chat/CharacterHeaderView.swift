//
//  CharacterHeaderView.swift
//  Kid Chat
//
//  Reusable header with large emoji avatar, character name, and status text.
//  When idle, avatar gently scales 1.0 ↔ 1.05 (~2s, repeats); animation stops when state changes.
//

import SwiftUI

// MARK: - Character header

/// A centered header showing an avatar, character name, and status from ConversationViewModel.
/// Uses a soft gradient background, rounded fonts, and state-based status color + scale animation.
struct CharacterHeaderView: View {
    @ObservedObject var conversationViewModel: ConversationViewModel

    /// Emoji used as the character avatar (e.g. 🤖 for Astro Buddy).
    private let avatarEmoji = "🤖"
    /// Character name shown below the avatar.
    private let characterName = "Astro Buddy"

    /// Avatar size: large and friendly for kids.
    private let avatarFontSize: CGFloat = 65
    /// Circle size for the avatar background (slightly larger than the emoji).
    private let avatarCircleSize: CGFloat = 88

    var body: some View {
        VStack(spacing: 10) {
            // Large emoji avatar with circular background and subtle shadow
            avatarView

            // Character name: rounded, bold, friendly
            Text(characterName)
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI)

            // Status text from ConversationViewModel; color depends on state
            Text(conversationViewModel.statusText)
                .font(.system(size: 16, weight: .medium, design: .rounded))
                .foregroundStyle(statusColor)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(
            LinearGradient(
                colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )
        )
        .animation(.easeInOut(duration: 0.3), value: conversationViewModel.state)
    }

    // MARK: - Avatar (emoji + circle + shadow; idle = gentle breathing scale)

    private var avatarView: some View {
        Group {
            if conversationViewModel.state == .idle {
                TimelineView(.animation(minimumInterval: 0.033)) { context in
                    let t = context.date.timeIntervalSinceReferenceDate
                    let scale = 1.0 + 0.025 * (1 + cos(.pi * t))
                    avatarBody.scaleEffect(scale)
                }
            } else {
                avatarBody
                    .scaleEffect(1.04)
                    .animation(.easeInOut(duration: 0.3), value: conversationViewModel.state)
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
        switch conversationViewModel.state {
        case .idle: return .gray
        case .listening: return .red
        case .thinking: return .orange
        case .speaking: return Color(red: 0.6, green: 0.4, blue: 0.9) // purple
        }
    }
}

// MARK: - Preview

#Preview {
    CharacterHeaderView(conversationViewModel: ConversationViewModel())
        .padding()
}
