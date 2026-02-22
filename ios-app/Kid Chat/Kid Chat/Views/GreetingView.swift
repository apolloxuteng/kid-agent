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
    /// Welcome screen with "Tell me a story" / "Ask anything".
    case greeting
    /// Chat screen.
    case chatting
}

/// Which greeting button the user tapped (so chat can e.g. auto-send "Tell me a story").
enum GreetingStarter {
    case story
    case askAnything
}

// MARK: - Greeting view

/// Welcome screen: avatar, greeting, subtitle, and two large buttons that call onStartChat(starter).
struct GreetingView: View {
    /// Called when the user taps a button. Pass .story or .askAnything so chat can start accordingly.
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

                // Two large full-width buttons
                VStack(spacing: 16) {
                    greetingButton(emoji: "📖", title: "Tell me a story", starter: .story)
                    greetingButton(emoji: "❓", title: "Ask anything", starter: .askAnything)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 48)
            }
        }
    }

    /// One large rounded button; triggers onStartChat(starter) when pressed.
    private func greetingButton(emoji: String, title: String, starter: GreetingStarter) -> some View {
        Button(action: { onStartChat(starter) }) {
            HStack(spacing: 12) {
                Text(emoji)
                    .font(.system(size: 28))
                Text(title)
                    .font(.system(size: 22, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 20)
            .background(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(buttonColor.gradient)
            )
            .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 4)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Preview

#Preview {
    GreetingView(onStartChat: { _ in })
}
