//
//  ContentView.swift
//  Kid Chat
//
//  Kid-friendly chat UI: soft colors, rounded shapes, clear states.
//  Designed for ages 3–7:
//  - Large tap targets (e.g. 64pt mic, big send) for easier tapping.
//  - Rounded typography and 18–20pt font for readability.
//  - Sufficient contrast (white/orange on green/orange) for accessibility.
//

import SwiftUI

// MARK: - Kid-friendly color theme (calm, not saturated)

/// Soft playful palette: pastel blue background, warm orange for user, soft green for AI.
/// Gentle gradients improve depth and feel friendlier than flat colors.
enum KidTheme {
    static let backgroundTop = Color(red: 0.85, green: 0.92, blue: 1.0)      // pastel blue
    static let backgroundBottom = Color(red: 0.92, green: 0.95, blue: 1.0)   // lighter blue
    static let bubbleUserStart = Color(red: 1.0, green: 0.75, blue: 0.45)      // warm orange
    static let bubbleUserEnd = Color(red: 1.0, green: 0.65, blue: 0.35)
    static let bubbleAIStart = Color(red: 0.6, green: 0.88, blue: 0.7)        // soft green
    static let bubbleAIEnd = Color(red: 0.5, green: 0.82, blue: 0.6)
    static let bubbleTextUser = Color.white
    static let bubbleTextAI = Color(red: 0.15, green: 0.2, blue: 0.15)
    static let micIdle = Color(red: 0.35, green: 0.55, blue: 0.95)            // blue
    static let micListening = Color.red
    static let micSpeaking = Color(red: 0.6, green: 0.4, blue: 0.9)           // purple
}

// MARK: - Main view

struct ContentView: View {
    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var speechRecognizer = SpeechRecognizer()

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                // Soft gradient background (calm, not saturated)
                LinearGradient(
                    colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                VStack(spacing: 0) {
                    // Friendly header: emoji, title, status
                    chatHeader
                        .padding(.top, 8)
                        .padding(.bottom, 4)

                    messageList
                        .frame(maxHeight: .infinity)
                }

                // Input bar at bottom (above safe area)
                inputBar

                // Large floating mic button (kid-sized tap target)
                micButton
            }
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarHidden(true)
        }
    }

    // MARK: - Header (emoji + title + status)

    private var chatHeader: some View {
        VStack(spacing: 6) {
            Text("🐻")
                .font(.system(size: 44))
            Text("Chat Buddy")
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI)

            if viewModel.conversationState != .idle {
                Group {
                    if viewModel.conversationState == .thinking {
                        ThinkingDotsView()
                    } else {
                        Text(headerStatusText)
                            .font(.system(size: 16, weight: .medium, design: .rounded))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var headerStatusText: String {
        switch viewModel.conversationState {
        case .idle: return ""
        case .listening: return "Listening…"
        case .thinking: return ""
        case .speaking: return "Speaking…"
        }
    }

    // MARK: - Message list

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(viewModel.messages) { message in
                        MessageBubble(message: message)
                            .id(message.id)
                            .transition(.asymmetric(
                                insertion: .opacity
                                    .combined(with: .move(edge: .bottom))
                                    .combined(with: .scale(scale: 0.96)),
                                removal: .opacity
                            ))
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
                .padding(.bottom, 200)
            }
            .modifier(BottomScrollAnchorModifier())
            .onChange(of: viewModel.messages.count) { _ in
                if let last = viewModel.messages.last {
                    withAnimation(.easeOut(duration: 0.35)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
        .scrollDismissesKeyboard(.interactively)
    }

    // MARK: - Input bar (text field + send)

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 12) {
            TextField("Message", text: $viewModel.inputText, axis: .vertical)
                .font(.system(size: 18, weight: .medium, design: .rounded))
                .textFieldStyle(.plain)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color.white.opacity(0.9))
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .lineLimit(1 ... 4)
                .submitLabel(.send)
                .onSubmit { viewModel.sendMessage() }
                .onChange(of: speechRecognizer.isRecording) { _ in
                    if speechRecognizer.isRecording {
                        viewModel.inputText = speechRecognizer.transcript
                    }
                    viewModel.setConversationState(speechRecognizer.isRecording ? .listening : .idle)
                }
                .onChange(of: speechRecognizer.transcript) { _ in
                    if speechRecognizer.isRecording {
                        viewModel.inputText = speechRecognizer.transcript
                    }
                }

            Button {
                viewModel.sendMessage()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 36))
                    .foregroundStyle(KidTheme.micIdle)
            }
            .disabled(
                viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || viewModel.isLoading
                || viewModel.conversationState == .speaking
            )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .padding(.bottom, 8)
        .background(
            LinearGradient(
                colors: [KidTheme.backgroundBottom.opacity(0.98), KidTheme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }

    // MARK: - Floating mic (large tap target, state-based color)

    private var micButton: some View {
        let isListening = speechRecognizer.isRecording
        let isSpeaking = viewModel.conversationState == .speaking
        let color: Color = isListening ? KidTheme.micListening : (isSpeaking ? KidTheme.micSpeaking : KidTheme.micIdle)

        return Button {
            speechRecognizer.toggleRecording()
        } label: {
            Image(systemName: "mic.fill")
                .font(.system(size: 28))
                .foregroundStyle(.white)
                .frame(width: 64, height: 64)
                .background(
                    Circle()
                        .fill(color.gradient)
                        .shadow(color: color.opacity(0.4), radius: isListening ? 12 : 6)
                )
        }
        .disabled(viewModel.isLoading || isSpeaking)
        .padding(.bottom, 100)
        .scaleEffect(isListening ? 1.08 : 1.0)
        .animation(.easeInOut(duration: 0.3), value: isListening)
    }
}

// MARK: - Thinking dots (● ○ ○ → ○ ● ○ → ○ ○ ●), cycles every 0.4s

private struct ThinkingDotsView: View {
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

// MARK: - Message bubble (rounded, gradient, max width 75%, appearance animation)

/// User = warm orange (right), AI = soft green (left). Large rounded corners (22pt) and padding for readability.
/// Max width ~75% so lines don’t stretch too wide; large tap/read area for kids.
struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if message.isUser { Spacer(minLength: 48) }

            Text(message.text)
                .font(.system(size: 20, weight: .medium, design: .rounded))
                .foregroundStyle(message.isUser ? KidTheme.bubbleTextUser : KidTheme.bubbleTextAI)
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
                .background(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .fill(
                            message.isUser
                                ? LinearGradient(colors: [KidTheme.bubbleUserStart, KidTheme.bubbleUserEnd], startPoint: .topLeading, endPoint: .bottomTrailing)
                                : LinearGradient(colors: [KidTheme.bubbleAIStart, KidTheme.bubbleAIEnd], startPoint: .topLeading, endPoint: .bottomTrailing)
                        )
                )
                .frame(maxWidth: 280, alignment: message.isUser ? .trailing : .leading)

            if !message.isUser { Spacer(minLength: 48) }
        }
        .animation(.easeOut(duration: 0.25), value: message.id)
    }
}

// MARK: - iOS 17 scroll anchor

private struct BottomScrollAnchorModifier: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 17.0, *) {
            content.defaultScrollAnchor(.bottom)
        } else {
            content
        }
    }
}

#Preview {
    ContentView()
}
