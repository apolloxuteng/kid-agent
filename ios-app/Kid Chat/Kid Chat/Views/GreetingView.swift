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
    /// Welcome screen with three mode buttons.
    case greeting
    /// Chat screen.
    case chatting
}

/// Which greeting mode the user chose; chat may auto-send a starter message for the server.
enum GreetingStarter {
    /// Kid asks questions to get started; no auto-send.
    case questions
    /// Server starts the conversation with a funny joke.
    case joke
    /// Server teaches and stores a vocabulary word.
    case word
}

// MARK: - Greeting view

/// Welcome screen: avatar, greeting, subtitle, and three mode buttons that call onStartChat(starter).
struct GreetingView: View {
    @EnvironmentObject private var conversationSettings: ConversationSettings
    @EnvironmentObject private var profileManager: ProfileManager

    /// Called when the user taps a button. Pass the chosen mode so chat can start accordingly.
    var onStartChat: (GreetingStarter) -> Void
    /// Called when the user taps the back button to return to profile selection (choose user / add users).
    var onBackToProfileSelection: () -> Void

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
                // Return to profile selection (top left) — same pill style and position as Mode button in chat
                HStack {
                    Button(action: onBackToProfileSelection) {
                        Label("Back", systemImage: "chevron.left")
                            .font(.system(size: 16, weight: .medium, design: .rounded))
                    }
                    .modifier(ThemedHeaderButtonModifier(accentGradient: conversationSettings.accentGradient))
                    .accessibilityLabel("Back to profile selection")
                    .accessibilityHint("Returns to the screen where you choose or add a user")
                    Spacer(minLength: 0)
                }
                .padding(.leading, 12)
                .padding(.trailing, 4)
                .padding(.top, 8)
                .padding(.bottom, 4)

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

                // Three mode buttons: aligned row, visible pop-in and tap feedback
                LazyVGrid(columns: [
                    GridItem(.flexible(), spacing: 10),
                    GridItem(.flexible(), spacing: 10),
                    GridItem(.flexible(), spacing: 10),
                ], spacing: 10) {
                    greetingButton(emoji: "❓", title: "Ask", subtitle: "Questions", starter: .questions, delay: 0)
                    greetingButton(emoji: "😂", title: "Laugh", subtitle: "Jokes", starter: .joke, delay: 0.05)
                    greetingButton(emoji: "🔤", title: "Learn", subtitle: "New word", starter: .word, delay: 0.10)
                }
                .padding(.horizontal, 20)
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
            VStack(spacing: 6) {
                Text(emoji)
                    .font(.system(size: 28))
                Text(title)
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(0.9))
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .padding(.horizontal, 8)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
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
    GreetingView(onStartChat: { _ in }, onBackToProfileSelection: {})
        .environmentObject(ConversationSettings())
        .environmentObject(ProfileManager())
}
