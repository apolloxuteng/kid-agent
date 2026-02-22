//
//  GreetingView.swift
//  Kid Chat
//
//  Welcome screen shown when the app opens. Large avatar, greeting text,
//  and two big buttons to start chatting. Colorful gradient, centered layout.
//

import SwiftUI

// MARK: - App mode

/// App flow: profile selection → greeting → chat.
enum AppMode {
    /// Initial screen: choose which profile to use (or add one).
    case selectProfile
    /// Welcome screen with four mode buttons (Story, Knowledge, Question, Joke).
    case greeting
    /// Chat screen.
    case chatting
}

/// Which greeting mode the user chose; chat may auto-send a starter message for the server.
enum GreetingStarter {
    /// Server replies with a funny story.
    case story
    /// Server introduces a country, celebrity, or place in the world.
    case knowledge
    /// Kid asks questions to get started; no auto-send.
    case question
    /// Server starts the conversation with a funny joke.
    case joke
}

// MARK: - Greeting view

/// Welcome screen: avatar, greeting, subtitle, and four mode buttons that call onStartChat(starter).
struct GreetingView: View {
    @EnvironmentObject private var conversationSettings: ConversationSettings
    @EnvironmentObject private var profileManager: ProfileManager

    /// Called when the user taps a button. Pass the chosen mode so chat can start accordingly.
    var onStartChat: (GreetingStarter) -> Void

    /// Large avatar size so kids easily recognize "me" or "my character."
    private let avatarFontSize: CGFloat = 96

    /// Greeting text based on time of day: morning (< 12), afternoon (< 18), else evening.
    private var timeBasedGreeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        if hour < 12 { return "Good morning!" }
        if hour < 18 { return "Good afternoon!" }
        return "Good evening!"
    }

    var body: some View {
        ZStack {
            conversationSettings.conversationGradient
                .ignoresSafeArea()

            VStack(spacing: 28) {
                Spacer()

                // Big profile avatar (or default bear) — visible and personal
                Text(profileManager.activeProfile?.avatar ?? "🐻")
                    .font(.system(size: avatarFontSize))
                    .padding(.bottom, 8)
                    .scaleEffect(avatarScale)
                    .opacity(avatarOpacity)

                Text(timeBasedGreeting)
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)
                    .opacity(titleOpacity)
                    .offset(y: titleOffset)

                Text("Ready to learn something fun?")
                    .font(.system(size: 20, weight: .medium, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.9))
                    .opacity(subtitleOpacity)
                    .offset(y: subtitleOffset)

                Spacer()

                // Four mode buttons: visible pop-in and tap feedback
                VStack(spacing: 12) {
                    greetingButton(emoji: "📖", title: "Story Mode", subtitle: "Get a funny story", starter: .story, delay: 0)
                    greetingButton(emoji: "🌍", title: "Knowledge Mode", subtitle: "Learn about a country, person, or place", starter: .knowledge, delay: 0.08)
                    greetingButton(emoji: "❓", title: "Question Mode", subtitle: "Ask me anything", starter: .question, delay: 0.16)
                    greetingButton(emoji: "😂", title: "Joke Mode", subtitle: "Hear a funny joke", starter: .joke, delay: 0.24)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 48)
            }
        }
        .onAppear {
            withAnimation(.easeOut(duration: 0.4)) {
                avatarScale = 1.0
                avatarOpacity = 1.0
            }
            withAnimation(.easeOut(duration: 0.35).delay(0.15)) {
                titleOpacity = 1.0
                titleOffset = 0
                subtitleOpacity = 1.0
                subtitleOffset = 0
            }
        }
    }

    // MARK: - Entrance animation state (visible pop-in)
    @State private var avatarScale: CGFloat = 0.8
    @State private var avatarOpacity: Double = 0
    @State private var titleOpacity: Double = 0
    @State private var titleOffset: CGFloat = 12
    @State private var subtitleOpacity: Double = 0
    @State private var subtitleOffset: CGFloat = 8

    /// One rounded button with optional subtitle; visible pop-in and tap bounce.
    private func greetingButton(emoji: String, title: String, subtitle: String, starter: GreetingStarter, delay: Double) -> some View {
        Button(action: { onStartChat(starter) }) {
            HStack(spacing: 12) {
                Text(emoji)
                    .font(.system(size: 26))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 18, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    Text(subtitle)
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(.white.opacity(0.9))
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .padding(.horizontal, 16)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(conversationSettings.accentGradient)
            )
            .shadow(color: .black.opacity(0.12), radius: 6, x: 0, y: 3)
        }
        .buttonStyle(GreetingButtonTapStyle(delay: delay))
    }
}

// MARK: - Visible tap feedback: scale down then spring back (kids can see "I pressed it")
private struct GreetingButtonTapStyle: ButtonStyle {
    var delay: Double

    @State private var isPressed = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.92 : 1.0)
            .animation(.spring(response: 0.3, dampingFraction: 0.6), value: configuration.isPressed)
            .opacity(buttonOpacity)
            .scaleEffect(buttonScale)
            .onAppear {
                withAnimation(.easeOut(duration: 0.35).delay(0.3 + delay)) {
                    buttonScale = 1.0
                    buttonOpacity = 1.0
                }
            }
    }

    @State private var buttonScale: CGFloat = 0.9
    @State private var buttonOpacity: Double = 0
}

// MARK: - Preview

#Preview {
    GreetingView(onStartChat: { _ in })
        .environmentObject(ConversationSettings())
        .environmentObject(ProfileManager())
}
