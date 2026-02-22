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
    /// Called when the user taps a button. Pass the chosen mode so chat can start accordingly.
    var onStartChat: (GreetingStarter) -> Void

    /// Gradient for the greeting screen (colorful, kid-friendly).
    private let gradientTop = Color(red: 0.95, green: 0.85, blue: 1.0)      // soft lavender
    private let gradientBottom = Color(red: 0.85, green: 0.95, blue: 1.0)   // pastel blue
    /// Button background: warm and inviting.
    private let buttonColor = Color(red: 0.45, green: 0.65, blue: 0.95)

    /// Greeting text based on time of day: morning (< 12), afternoon (< 18), else evening.
    private var timeBasedGreeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        if hour < 12 { return "Good morning!" }
        if hour < 18 { return "Good afternoon!" }
        return "Good evening!"
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [gradientTop, gradientBottom],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            VStack(spacing: 28) {
                Spacer()

                // Large emoji avatar
                Text("🐻")
                    .font(.system(size: 80))
                    .padding(.bottom, 8)

                Text(timeBasedGreeting)
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)

                Text("Ready to learn something fun?")
                    .font(.system(size: 20, weight: .medium, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.9))

                Spacer()

                // Four mode buttons: Story, Knowledge, Question, Joke
                VStack(spacing: 12) {
                    greetingButton(emoji: "📖", title: "Story Mode", subtitle: "Get a funny story", starter: .story)
                    greetingButton(emoji: "🌍", title: "Knowledge Mode", subtitle: "Learn about a country, person, or place", starter: .knowledge)
                    greetingButton(emoji: "❓", title: "Question Mode", subtitle: "Ask me anything", starter: .question)
                    greetingButton(emoji: "😂", title: "Joke Mode", subtitle: "Hear a funny joke", starter: .joke)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 48)
            }
        }
    }

    /// One rounded button with optional subtitle; triggers onStartChat(starter) when pressed.
    private func greetingButton(emoji: String, title: String, subtitle: String, starter: GreetingStarter) -> some View {
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
                    .fill(buttonColor.gradient)
            )
            .shadow(color: .black.opacity(0.12), radius: 6, x: 0, y: 3)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Preview

#Preview {
    GreetingView(onStartChat: { _ in })
}
