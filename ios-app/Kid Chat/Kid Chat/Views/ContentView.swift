//
//  ContentView.swift
//  Kid Chat
//
//  Kid-friendly chat UI: soft gradient, rounded fonts, clear states.
//  Layout: VStack (header → ScrollView → input bar); mic button overlaid at bottom.
//  Full-screen gradient background; safe area padding respected. Rounded system font throughout.
//

import SwiftUI
import UIKit

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
    /// Send button scale for visible celebration when user sends a message.
    @State private var sendButtonScale: CGFloat = 1.0

    var body: some View {
        Group {
            switch appMode {
            case .selectProfile:
                ProfileSelectionView(onContinue: {
                    appMode = .greeting
                })
            case .greeting:
                GreetingView(
                    onStartChat: { starter in
                        pendingStarter = starter
                        appMode = .chatting
                    },
                    onBackToProfileSelection: {
                        appMode = .selectProfile
                    }
                )
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
            .onChange(of: viewModel.messages.last?.text) { _ in
                // Re-check when message text updates (streaming); emoji may appear only after "dog" etc. arrives.
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
                        viewModel.inputText = "Tell me a fact about the world"
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
                MessageBubble(message: message, accentGradient: conversationSettings.accentGradient)
                    .id(message.id)
                    .transition(MessageBubbleStyle.style(for: message.text).transition)
            }
        }
        .padding(.horizontal, 0)
        .padding(.top, 12)
        .padding(.bottom, 120)
    }

    // MARK: - Typeahead (kid-friendly: tap to select, not Tab)

    /// One suggestion chip: either complete the current word (replace) or append a phrase (next word).
    private enum TypeaheadItem: Hashable {
        case word(String)
        case phrase(String)
        var displayText: String {
            switch self {
            case .word(let s): return s
            case .phrase(let s): return s
            }
        }
    }

    /// Words offered as tap-to-select completions for the current word. Kid-friendly and common.
    private static let typeaheadWords: [String] = [
        "congratulations", "hello", "hi", "please", "thanks", "thank you", "yes", "no",
        "story", "stories", "joke", "jokes", "tell me", "what is", "how are you", "good morning", "good night",
        "dinosaur", "dinosaurs", "animal", "animals", "dog", "cat", "bird", "friend", "friends",
        "love", "happy", "sad", "cool", "awesome", "fun", "funny", "great", "amazing", "wow",
        "question", "questions", "help", "something", "everything", "everyone", "today", "tomorrow",
        "birthday", "present", "game", "play", "read", "book", "school", "home", "family",
        "mom", "dad", "brother", "sister", "grandma", "grandpa", "teacher", "friend"
    ]

    /// After last word X, suggest these phrases (tap appends). Kid-focused next-word / phrase completions.
    private static let typeaheadPhraseMap: [String: [String]] = [
        "tell": ["me a story", "me a joke", "me something"],
        "a": ["story", "joke", "funny story"],
        "what": ["is", "are"],
        "how": ["are you", "do you"],
        "good": ["morning", "night", "afternoon"],
        "thank": ["you"],
        "I": ["want", "like", "love"],
        "want": ["to hear", "to know", "a story"]
    ]

    /// Current word fragment being typed (last word in input, or whole input if no space).
    private func currentWordPrefix(from text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let lastSpace = trimmed.lastIndex(of: " ") else { return trimmed }
        return String(trimmed[trimmed.index(after: lastSpace)...])
    }

    /// Last complete token (word) in the input; used to look up phrase suggestions.
    private func lastToken(from text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return trimmed.split(separator: " ").last.map(String.init)
    }

    /// Replaces the current word with the selected suggestion.
    private func applyTypeaheadSuggestion(to text: String, suggestion: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let lastSpace = trimmed.lastIndex(of: " ") else { return suggestion }
        let before = String(trimmed[..<lastSpace])
        return before.isEmpty ? suggestion : before + " " + suggestion
    }

    /// Appends a phrase suggestion to the text (one space between).
    private func applyPhraseSuggestion(to text: String, phrase: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? phrase : trimmed + " " + phrase
    }

    /// Phrase/next-word suggestions when the last token matches a key (e.g. "tell" → "me a story").
    private func phraseSuggestions(for lastWord: String?) -> [String] {
        guard let word = lastWord, !word.isEmpty else { return [] }
        let key = word.lowercased()
        return ContentView.typeaheadPhraseMap[key] ?? []
    }

    /// Merged suggestions: kid list first (prefix match), then UITextChecker completions; deduped, up to 8.
    /// Min prefix length 1 so slow typers see suggestions earlier.
    private func mergedWordSuggestions(prefix: String, fullText: String) -> [String] {
        guard !prefix.isEmpty else { return [] }
        let lower = prefix.lowercased()

        // Kid list first (prioritized for relevance)
        let kidMatches = ContentView.typeaheadWords.filter { $0.lowercased().hasPrefix(lower) }

        // System completions (UITextChecker: system dictionary + learned words)
        var systemCompletions: [String] = []
        let trimmed = fullText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            let rangeStart: String.Index
            if let lastSpace = trimmed.lastIndex(of: " ") {
                rangeStart = trimmed.index(after: lastSpace)
            } else {
                rangeStart = trimmed.startIndex
            }
            let range = rangeStart..<trimmed.endIndex
            let nsRange = NSRange(range, in: trimmed)
            systemCompletions = UITextChecker().completions(forPartialWordRange: nsRange, in: trimmed, language: "en") ?? []
        }
        systemCompletions = systemCompletions.filter { $0.lowercased().hasPrefix(lower) }

        // Merge: kid first, then system, dedupe (case-insensitive), cap 8
        var seen = Set<String>()
        var result: [String] = []
        for w in kidMatches {
            let l = w.lowercased()
            if !seen.contains(l) { seen.insert(l); result.append(w) }
        }
        for w in systemCompletions {
            let l = w.lowercased()
            if !seen.contains(l) { seen.insert(l); result.append(w) }
        }
        return Array(result.prefix(8))
    }

    /// Combined suggestions: word completions (current word) + phrase/next-word when last token matches. Tap to select only.
    /// Word completions first (kid list + UITextChecker), then phrase suggestions; total cap 8.
    private var typeaheadSuggestions: [TypeaheadItem] {
        let text = viewModel.inputText
        let prefix = currentWordPrefix(from: text)
        let lastWord = lastToken(from: text)

        var items: [TypeaheadItem] = []
        if !prefix.isEmpty {
            items = mergedWordSuggestions(prefix: prefix, fullText: text).map { .word($0) }
        }
        let phraseList = phraseSuggestions(for: lastWord).map { TypeaheadItem.phrase($0) }
        items += phraseList
        return Array(items.prefix(8))
    }

    /// Current word prefix for typeahead; used so the suggestion row explicitly depends on input and updates as user types.
    private var typeaheadPrefix: String {
        currentWordPrefix(from: viewModel.inputText)
    }

    // MARK: - Input bar (text field + send)

    private var inputBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Typeahead: tap to select a word or phrase (kid-friendly, no Tab); updates as user types.
            if !typeaheadSuggestions.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(typeaheadSuggestions, id: \.self) { item in
                            Button {
                                switch item {
                                case .word(let s):
                                    viewModel.inputText = applyTypeaheadSuggestion(to: viewModel.inputText, suggestion: s)
                                case .phrase(let s):
                                    viewModel.inputText = applyPhraseSuggestion(to: viewModel.inputText, phrase: s)
                                }
                            } label: {
                                Text(item.displayText)
                                    .font(.system(size: 15, weight: .medium, design: .rounded))
                                    .foregroundStyle(KidTheme.bubbleTextAI)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 8)
                                    .background(Color.white.opacity(0.95))
                                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Use \(item.displayText)")
                            .accessibilityHint("Tap to insert")
                        }
                    }
                    .padding(.horizontal, 2)
                }
                .frame(height: 40)
                .id(typeaheadPrefix)
            }

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
                    // Visible celebration: scale up then spring back so kids see "my message was sent"
                    withAnimation(.spring(response: 0.25, dampingFraction: 0.6)) {
                        sendButtonScale = 1.2
                    }
                    viewModel.sendMessage()
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) {
                            sendButtonScale = 1.0
                        }
                    }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 36))
                        .foregroundStyle(conversationSettings.accentGradient)
                        .scaleEffect(sendButtonScale)
                }
                .accessibilityLabel("Send message")
                .accessibilityHint("Sends your message to the assistant")
                .disabled(
                    viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || viewModel.isLoading
                    || viewModel.conversationState == .speaking
                )
            }
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
            // If agent is speaking, one tap stops TTS and immediately starts listening
            if viewModel.conversationState == .speaking {
                viewModel.stopSpeaking()
            }
            if !speechRecognizer.isRecording {
                viewModel.setConversationState(.listening)
            }
            speechRecognizer.toggleRecording()
        }, idleGradient: conversationSettings.accentGradient)
            .disabled(viewModel.isLoading)
    }
}

// MARK: - Themed header button (pill with accent gradient, used for Mode, Settings, and Back)

/// Applies theme accent gradient, pill shape, and soft shadow so header buttons match the selected theme.
struct ThemedHeaderButtonModifier: ViewModifier {
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

    /// Match whole words only so "man" doesn't trigger inside "many"/"woman", "person" not in "personal".
    static func keywordEmoji(for text: String) -> String? {
        let words = text.lowercased()
            .split(whereSeparator: { $0.isWhitespace || $0.isPunctuation })
            .map { String($0) }
        return pairs.first { pair in
            words.contains { $0 == pair.keyword }
        }?.emoji
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
    var accentGradient: LinearGradient? = nil

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
        VStack(alignment: message.isUser ? .trailing : .leading, spacing: 10) {
            if let data = message.imageData, let uiImage = UIImage(data: data) {
                Image(uiImage: uiImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 400, maxHeight: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            if !message.text.isEmpty {
                Text(message.text)
                    .font(.system(size: 20, weight: .medium, design: .rounded))
                    .foregroundStyle(message.isUser ? KidTheme.bubbleTextUser : KidTheme.bubbleTextAI)
            }
        }
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
        .overlay {
            if !message.isUser, let gradient = accentGradient {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(gradient, lineWidth: 2.5)
            }
        }
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
