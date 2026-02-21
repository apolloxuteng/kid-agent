//
//  ContentView.swift
//  Kid Chat
//
//  Kid-friendly chat UI: soft gradient, rounded fonts, clear states.
//  Layout: VStack (header → ScrollView → input bar); mic button overlaid at bottom.
//  Full-screen gradient background; safe area padding respected. Rounded system font throughout.
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
    @State private var appMode: AppMode = .greeting
    /// When user taps "Tell me a story", we send this once when chat appears so the LLM starts with a story.
    @State private var pendingStarter: GreetingStarter?
    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var conversationViewModel = ConversationViewModel()
    @StateObject private var speechRecognizer = SpeechRecognizer()

    var body: some View {
        Group {
            if appMode == .greeting {
                GreetingView(onStartChat: { starter in
                    pendingStarter = starter
                    appMode = .chatting
                })
            } else {
                chatView
            }
        }
    }

    /// Chat UI: header, messages, input bar, mic. Shown when appMode == .chatting.
    private var chatView: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                // Soft gradient background for entire screen
                LinearGradient(
                    colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                // Main content: header, messages, input bar (mic is overlaid below so conversation gets more space)
                VStack(spacing: 0) {
                    CharacterHeaderView(conversationViewModel: conversationViewModel)
                        .padding(.top, 8)
                        .padding(.bottom, 4)

                    ScrollViewReader { proxy in
                        ScrollView {
                            messageListContent(proxy: proxy)
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
                    .frame(maxHeight: .infinity)

                    inputBar
                }
                .padding(.horizontal, 16)

                // Mic button floats at bottom (does not take space from conversation)
                micButton
                    .padding(.bottom, 24)
            }
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarHidden(true)
            .onChange(of: viewModel.conversationState) { newState in
                conversationViewModel.state = newState
            }
            .onAppear {
                if pendingStarter == .story {
                    viewModel.inputText = "Tell me a short story"
                    viewModel.sendMessage()
                    pendingStarter = nil
                }
            }
        }
    }

    // MARK: - Message list (content inside ScrollView; proxy passed from parent)

    @ViewBuilder
    private func messageListContent(proxy: ScrollViewProxy) -> some View {
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
        .padding(.horizontal, 0)
        .padding(.top, 12)
        .padding(.bottom, 120)
    }

    // MARK: - Input bar (text field + send)

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 12) {
            TextField("Message", text: $viewModel.inputText, axis: .vertical)
                .font(.system(size: 18, weight: .medium, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI)
                .textFieldStyle(.plain)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color.white.opacity(0.9))
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .lineLimit(1 ... 4)
                .submitLabel(.send)
                .onSubmit { viewModel.sendMessage() }
                .onChange(of: speechRecognizer.isRecording) { isRecording in
                    if isRecording {
                        viewModel.inputText = speechRecognizer.transcript
                        viewModel.setConversationState(.listening)
                        conversationViewModel.state = .listening
                    } else {
                        viewModel.setConversationState(.idle)
                        conversationViewModel.state = .idle
                        // Auto-send when user finishes talking (voice input only; manual typing still uses Send)
                        let text = viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                        if !text.isEmpty {
                            viewModel.sendMessage()
                        }
                    }
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
                || conversationViewModel.state == .speaking
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
        LargeMicButton(state: conversationViewModel.state, onTap: {
            if !speechRecognizer.isRecording {
                conversationViewModel.state = .listening
                viewModel.setConversationState(.listening)
            }
            speechRecognizer.toggleRecording()
        })
            .disabled(viewModel.isLoading || conversationViewModel.state == .speaking)
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
