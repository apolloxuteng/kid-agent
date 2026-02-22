//
//  ThinkingDotsView.swift
//  Kid Chat
//
//  Animated dots (● ○ ○ → ○ ● ○ → ○ ○ ●) for "thinking" state. Shown in the header when waiting for a reply.
//

import SwiftUI

/// Cycling dots to indicate the app is thinking. Use when conversation state is .thinking.
struct ThinkingDotsView: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 0.4)) { context in
            let step = Int(context.date.timeIntervalSinceReferenceDate / 0.4) % 3
            HStack(spacing: 6) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(i == step ? KidTheme.bubbleTextAI : KidTheme.bubbleTextAI.opacity(0.3))
                        .frame(width: 8, height: 8)
                }
            }
        }
        .font(.system(size: 16, weight: .medium, design: .rounded))
    }
}

#Preview {
    ThinkingDotsView()
        .padding()
}
