//
//  ContentView.swift
//  Kid Chat
//
//  Kid-friendly chat UI: soft gradient, rounded fonts, clear states.
//  Layout: VStack (header → ScrollView → input bar); mic button overlaid at bottom.
//  Full-screen gradient background; safe area padding respected. Rounded system font throughout.
//

import SwiftUI

// MARK: - Main view

struct ContentView: View {
    @EnvironmentObject private var profileManager: ProfileManager
    @EnvironmentObject private var conversationSettings: ConversationSettings
    @State private var appMode: AppMode = .selectProfile
    /// When user picks a greeting mode, we may send a starter message once when chat appears (story/knowledge/joke); question mode has no auto-send.
    @State private var pendingStarter: GreetingStarter?
    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var speechRecognizer = SpeechRecognizer()
    /// When true, the profile picker sheet is presented (triggered by tapping avatar in header).
    @State private var showProfilePicker = false
    /// When true, the conversation settings sheet is presented (voice, mute, background).
    @State private var showSettings = false
    /// When non-nil, show this emoji floating up from bottom center; one per last AI message.
    @State private var floatingEmoji: String? = nil
    /// Avoid re-triggering animation for the same message.
    @State private var lastAnimatedMessageID: UUID? = nil
    /// Vertical offset for floating emoji (0 = bottom, negative = moves up).
    @State private var floatingEmojiOffset: CGFloat = 0

    var body: some View {
        Group {
            switch appMode {
            case .selectProfile:
                ProfileSelectionView(onContinue: {
                    appMode = .greeting
                })
            case .greeting:
                GreetingView(onStartChat: { starter in
                    pendingStarter = starter
                    appMode = .chatting
                })
            case .chatting:
                chatView
            }
        }
    }

    /// Returns to the mode-selection screen and restarts the conversation (clears messages and state).
    private func goBackToModeSelection() {
        viewModel.cancelRequest()
        viewModel.messages = []
        viewModel.inputText = ""
        viewModel.isLoading = false
        viewModel.setConversationState(.idle)
        appMode = .greeting
    }

    /// Chat UI: header, messages, input bar, mic. Shown when appMode == .chatting.
    private var chatView: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                // Gradient background from conversation settings (pastel blue, lavender, mint, etc.)
                conversationSettings.conversationGradient
                    .ignoresSafeArea()

                // Main content: back bar, header, messages, input bar (mic is overlaid below)
                VStack(spacing: 0) {
                    // Back to mode selection (left); Settings (right) — themed pill style
                    HStack {
                        Button(action: goBackToModeSelection) {
                            Label("Mode", systemImage: "chevron.left")
                                .font(.system(size: 16, weight: .medium, design: .rounded))
                        }
                        .modifier(ThemedHeaderButtonModifier(accentGradient: conversationSettings.accentGradient))
                        .accessibilityLabel("Back to mode selection")
                        .accessibilityHint("Returns to choose Story, Knowledge, Question, or Joke mode and starts a new conversation")
                        Spacer(minLength: 0)
                        Button(action: { showSettings = true }) {
                            Image(systemName: "gearshape")
                                .font(.system(size: 20, weight: .medium))
                        }
                        .modifier(ThemedHeaderButtonModifier(accentGradient: conversationSettings.accentGradient))
                        .accessibilityLabel("Settings")
                        .accessibilityHint("Voice, mute, and theme options")
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 8)
                    .padding(.bottom, 2)

                    CharacterHeaderView(conversationState: viewModel.conversationState, statusText: viewModel.statusText, onAvatarTap: {
                        showProfilePicker = true
                    }, backgroundGradient: conversationSettings.conversationGradient)
                    .padding(.top, 4)
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
                        .onChange(of: viewModel.messages.last?.text) { _ in
                            // During streaming we update the same message in place; scroll so the latest text stays visible
                            if let last = viewModel.messages.last {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .frame(maxHeight: .infinity)

                    inputBar
                }
                .padding(.horizontal, 16)

                // Floating emoji overlay: bottom center, animates upward and exits at top
                floatingEmojiOverlay

                // Mic button floats at bottom (does not take space from conversation)
                micButton
                    .padding(.bottom, 24)
            }
            .onChange(of: viewModel.messages.last?.id) { _ in
                guard let last = viewModel.messages.last, !last.isUser else { return }
                if last.id == lastAnimatedMessageID { return }
                if let emoji = FloatingEmojiKeywords.keywordEmoji(for: last.text) {
                    lastAnimatedMessageID = last.id
                    floatingEmojiOffset = 0
                    floatingEmoji = emoji
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarHidden(true)
            .onChange(of: profileManager.activeProfile?.id) { _ in
                viewModel.cancelRequest()
                viewModel.activeProfileId = profileManager.activeProfile?.id
                // Switching profile resets chat UI so each child gets a fresh conversation.
                viewModel.messages = []
                viewModel.inputText = ""
                viewModel.isLoading = false
                viewModel.setConversationState(.idle)
            }
            .onChange(of: conversationSettings.selectedVoiceIdentifier) { _ in
                viewModel.updateVoiceAndMute(voiceIdentifier: conversationSettings.selectedVoiceIdentifier, muted: conversationSettings.isAgentMuted)
            }
            .onChange(of: conversationSettings.isAgentMuted) { _ in
                viewModel.updateVoiceAndMute(voiceIdentifier: conversationSettings.selectedVoiceIdentifier, muted: conversationSettings.isAgentMuted)
            }
            .onDisappear {
                viewModel.cancelRequest()
            }
            .sheet(isPresented: $showProfilePicker) {
                ProfilePickerView()
            }
            .sheet(isPresented: $showSettings) {
                ConversationSettingsView(settings: conversationSettings)
            }
            .onAppear {
                viewModel.updateVoiceAndMute(voiceIdentifier: conversationSettings.selectedVoiceIdentifier, muted: conversationSettings.isAgentMuted)
                viewModel.activeProfileId = profileManager.activeProfile?.id
                if let starter = pendingStarter {
                    switch starter {
                    case .story:
                        viewModel.inputText = "Tell me a funny story"
                        viewModel.sendMessage()
                    case .knowledge:
                        viewModel.inputText = "Introduce me to something interesting from the world—a country, a famous person, or a cool place."
                        viewModel.sendMessage()
                    case .question:
                        break // Kid asks questions; no auto-send
                    case .joke:
                        viewModel.inputText = "Tell me a funny joke"
                        viewModel.sendMessage()
                    }
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
                    .transition(MessageBubbleStyle.style(for: message.text).transition)
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
                    } else {
                        viewModel.setConversationState(.idle)
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
                    .foregroundStyle(conversationSettings.accentGradient)
            }
            .accessibilityLabel("Send message")
            .accessibilityHint("Sends your message to the assistant")
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

    // MARK: - Floating emoji overlay (keyword-triggered, animates up and out)

    @ViewBuilder
    private var floatingEmojiOverlay: some View {
        if let emoji = floatingEmoji {
            VStack {
                Spacer(minLength: 0)
                Text(emoji)
                    .font(.system(size: 70))
                    .offset(y: floatingEmojiOffset)
            }
            .frame(maxWidth: .infinity)
            .allowsHitTesting(false)
            .onAppear {
                withAnimation(.easeInOut(duration: 2.5)) {
                    floatingEmojiOffset = -UIScreen.main.bounds.height
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                    floatingEmoji = nil
                    floatingEmojiOffset = 0
                }
            }
        }
    }

    // MARK: - Floating mic (large tap target, state-based color)

    private var micButton: some View {
        LargeMicButton(state: viewModel.conversationState, onTap: {
            // If agent is speaking, tap stops TTS (useful for long replies)
            if viewModel.conversationState == .speaking {
                viewModel.stopSpeaking()
                return
            }
            if !speechRecognizer.isRecording {
                viewModel.setConversationState(.listening)
            }
            speechRecognizer.toggleRecording()
        })
            .disabled(viewModel.isLoading)
    }
}

// MARK: - Themed header button (pill with accent gradient, used for Mode and Settings)

/// Applies theme accent gradient, pill shape, and soft shadow so header buttons match the selected theme.
private struct ThemedHeaderButtonModifier: ViewModifier {
    let accentGradient: LinearGradient

    func body(content: Content) -> some View {
        content
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(accentGradient)
            )
            .shadow(color: .black.opacity(0.12), radius: 6, x: 0, y: 3)
    }
}

// MARK: - Keyword → floating emoji (first match, case-insensitive)

private enum FloatingEmojiKeywords {
    /// Order matters: first match wins. (keyword, emoji).
    static let pairs: [(keyword: String, emoji: String)] = [
        // People / characters
        ("person", "🧑"), ("human", "🧑"), ("boy", "🧑"), ("girl", "🧑"), ("baby", "👶"), ("kid", "🧒"), ("child", "🧒"), ("man", "👨"), ("woman", "👩"), ("friend", "🧑"),
        // Animals – big / wild
        ("tiger", "🐯"), ("lion", "🦁"), ("bear", "🐻"), ("elephant", "🐘"), ("monkey", "🐵"), ("gorilla", "🦍"), ("wolf", "🐺"), ("fox", "🦊"), ("deer", "🦌"), ("rabbit", "🐰"), ("frog", "🐸"), ("snake", "🐍"), ("dinosaur", "🦕"), ("dragon", "🐉"), ("unicorn", "🦄"),
        // Animals – pets / farm
        ("dog", "🐕"), ("cat", "🐱"), ("bird", "🐦"), ("fish", "🐟"), ("horse", "🐴"), ("cow", "🐄"), ("pig", "🐷"), ("sheep", "🐑"), ("mouse", "🐭"), ("bee", "🐝"), ("butterfly", "🦋"),
        // Nature / weather
        ("sun", "☀️"), ("moon", "🌙"), ("star", "⭐️"), ("cloud", "☁️"), ("rainbow", "🌈"), ("tree", "🌳"), ("flower", "🌸"), ("fire", "🔥"), ("snow", "❄️"), ("rain", "🌧️"), ("ocean", "🌊"),
        // Objects / story
        ("castle", "🏰"), ("crown", "👑"), ("key", "🔑"), ("book", "📖"), ("balloon", "🎈"), ("cake", "🎂"), ("gift", "🎁"), ("rocket", "🚀"), ("car", "🚗"), ("boat", "⛵️"),
        // Emotions / actions
        ("happy", "😊"), ("love", "❤️"), ("magic", "✨"),
    ]

    static func keywordEmoji(for text: String) -> String? {
        let lower = text.lowercased()
        return pairs.first { lower.contains($0.keyword) }?.emoji
    }
}

// MARK: - Content-based bubble style (app-side only; no server)

enum MessageBubbleStyle {
    case calm
    case excited
    case question

    private static let excitedKeywords = ["yay", "great", "awesome", "wow", "love", "happy", "fun", "cool", "amazing"]

    static func style(for text: String) -> MessageBubbleStyle {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if t.contains("!") || excitedKeywords.contains(where: { t.contains($0) }) { return .excited }
        if t.contains("?") { return .question }
        return .calm
    }

    var transition: AnyTransition {
        switch self {
        case .calm:
            return .asymmetric(
                insertion: .opacity.combined(with: .move(edge: .bottom)).combined(with: .scale(scale: 0.96)),
                removal: .opacity
            )
        case .excited:
            return .asymmetric(
                insertion: .opacity.combined(with: .move(edge: .bottom)).combined(with: .scale(scale: 0.9)),
                removal: .opacity
            )
        case .question:
            return .asymmetric(
                insertion: .opacity.combined(with: .move(edge: .bottom)).combined(with: .scale(scale: 0.98)),
                removal: .opacity
            )
        }
    }
}

// MARK: - Message bubble (rounded, gradient, content-based entrance and optional pulse)

/// User = warm orange (right), AI = soft green (left). Large rounded corners (22pt) and padding for readability.
/// Max width ~75% so lines don’t stretch too wide; large tap/read area for kids.
struct MessageBubble: View {
    let message: ChatMessage

    private var bubbleStyle: MessageBubbleStyle {
        MessageBubbleStyle.style(for: message.text)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if message.isUser { Spacer(minLength: 32) }

            bubbleContent
                .modifier(ExcitedPulseModifier(apply: !message.isUser && bubbleStyle == .excited))
                .accessibilityLabel(message.isUser ? "You said: \(message.text)" : "Reply: \(message.text)")
                .accessibilityHint("Message in the conversation")

            if !message.isUser { Spacer(minLength: 32) }
        }
        .animation(.easeOut(duration: 0.25), value: message.id)
    }

    private var bubbleContent: some View {
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
            .frame(maxWidth: 340, alignment: message.isUser ? .trailing : .leading)
    }
}

/// Very subtle scale pulse (1.0 to 1.02) for AI + excited bubbles only; ~1.5s cycle.
private struct ExcitedPulseModifier: ViewModifier {
    var apply: Bool

    func body(content: Content) -> some View {
        if apply {
            content.modifier(ExcitedPulseAnimation())
        } else {
            content
        }
    }
}

private struct ExcitedPulseAnimation: ViewModifier {
    func body(content: Content) -> some View {
        TimelineView(.animation(minimumInterval: 0.05)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let scale = 1.0 + 0.01 * (1 + cos(.pi * t / 1.5))
            content.scaleEffect(scale)
        }
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
        .environmentObject(ProfileManager())
        .environmentObject(ConversationSettings())
}
