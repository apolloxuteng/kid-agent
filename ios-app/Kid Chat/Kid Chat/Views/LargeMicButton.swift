//
//  LargeMicButton.swift
//  Kid Chat
//
//  A large circular mic button whose appearance changes with ConversationState.
//  Idle = blue, Listening = red + pulse, Thinking = orange + disabled, Speaking = purple + glow.
//  Calls onTap when the user taps (when not disabled). Accessibility: "Tap to talk".
//

import SwiftUI

// MARK: - Large mic button

/// Large circular button (80–100pt) with mic icon. Floating look; state-based color and animation.
struct LargeMicButton: View {
    /// Current conversation state: drives background color, pulse, glow, and disabled state.
    let state: ConversationState
    /// Called when the user taps the button. Not called when state is .thinking (disabled).
    let onTap: () -> Void
    /// When provided, used for idle state so mic matches the app theme; nil = KidTheme.micIdle.
    var idleGradient: LinearGradient? = nil

    /// Button size: 90pt (within 80–100pt). Large, easy for kids to tap. Floating look: parent adds .padding(.bottom, 100).
    private let size: CGFloat = 90
    /// Icon size inside the circle.
    private let iconFontSize: CGFloat = 32

    var body: some View {
        Button(action: onTap) {
            Image(systemName: "mic.fill")
                .font(.system(size: iconFontSize))
                .foregroundStyle(.white)
                .frame(width: size, height: size)
                .background(circleBackground)
                .shadow(color: shadowColor, radius: shadowRadius, x: 0, y: 4)
        }
        .buttonStyle(.plain)
        .disabled(state == .thinking)
        .modifier(ListeningPulseModifier(state: state))
        .animation(.easeInOut(duration: 0.3), value: state)
        .accessibilityLabel("Tap to talk")
        .accessibilityHint("Starts or stops voice input; when assistant is speaking, tap to stop")
    }

    // MARK: - Background and shadow by state

    private var circleBackground: some View {
        Group {
            if state == .idle, let gradient = idleGradient {
                Circle().fill(gradient)
            } else {
                Circle().fill(backgroundColor.gradient)
            }
        }
    }

    /// Background color: red (listening), orange (thinking), purple (speaking). Idle uses idleGradient when provided.
    private var backgroundColor: Color {
        switch state {
        case .idle: return KidTheme.micIdle
        case .listening: return KidTheme.micListening
        case .thinking: return .orange
        case .speaking: return KidTheme.micSpeaking
        }
    }

    /// Shadow color: matches state; stronger for speaking (glow). Idle with theme uses soft shadow.
    private var shadowColor: Color {
        switch state {
        case .idle: return (idleGradient != nil ? Color.black : backgroundColor).opacity(0.35)
        case .listening: return backgroundColor.opacity(0.5)
        case .thinking: return backgroundColor.opacity(0.3)
        case .speaking: return KidTheme.micSpeaking.opacity(0.6)
        }
    }

    /// Shadow radius: larger for speaking (glowing shadow).
    private var shadowRadius: CGFloat {
        switch state {
        case .idle: return 8
        case .listening: return 12
        case .thinking: return 6
        case .speaking: return 16
        }
    }

    // MARK: - Pulsing (listening only)

    // Pulse is applied via ListeningPulseModifier below: easeInOut-style scale 1.0 ↔ 1.08.
}

// MARK: - Repeating pulse when listening

/// When state is .listening, applies a gentle repeating scale (1.0 ↔ 1.08) using a timeline
/// so it oscillates with easeInOut-style motion. When not listening, no scale applied.
private struct ListeningPulseModifier: ViewModifier {
    let state: ConversationState
    private let pulseDuration: Double = 0.6

    func body(content: Content) -> some View {
        if state == .listening {
            TimelineView(.animation(minimumInterval: 0.05)) { context in
                let t = context.date.timeIntervalSinceReferenceDate
                let scale = 1.0 + 0.04 * (1 + cos(2 * Double.pi * t / pulseDuration))
                content.scaleEffect(scale)
            }
        } else {
            content
        }
    }
}

// MARK: - Preview

#Preview {
    VStack(spacing: 20) {
        LargeMicButton(state: .idle, onTap: {})
        LargeMicButton(state: .listening, onTap: {})
        LargeMicButton(state: .thinking, onTap: {})
        LargeMicButton(state: .speaking, onTap: {})
    }
    .padding()
}
