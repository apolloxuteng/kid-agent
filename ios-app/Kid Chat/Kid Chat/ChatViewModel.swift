//
//  ChatViewModel.swift
//  Kid Chat
//
//  Holds chat state and talks to the backend. Manages conversation pacing
//  (thinking delay, speaking state) so the AI feels like a calm partner.
//

import Foundation

/// Request body we send to the backend (must include profile_id for per-child memory).
private struct ChatRequest: Encodable {
    let message: String
    let profile_id: String  // UUID string of the active child profile; backend stores data under data/profiles/{profile_id}/
}

/// Response body we get back from the backend.
private struct ChatResponse: Decodable {
    let reply: String
}

/// Connects the UI to the chat backend: stores messages, handles send, updates UI.
class ChatViewModel: ObservableObject {

    // MARK: - Configuration
    /// Fixed IP from router DHCP reservation (does not change after restart). Update the IP below if your reserved address is different.
    /// Run backend: uvicorn server:app --host 0.0.0.0
    static let SERVER_URL = "http://192.168.68.71:8000/chat"

    // MARK: - Published state (SwiftUI observes these and redraws when they change)

    /// All messages in the conversation (user and AI).
    @Published var messages: [ChatMessage] = []

    /// Current text in the input field.
    @Published var inputText: String = ""

    /// True while we’re waiting for the backend reply (used to disable Send and show loading).
    @Published var isLoading: Bool = false

    /// Drives status text and button states (listening / thinking / speaking).
    @Published var conversationState: ConversationState = .idle

    /// Active child profile id; set by ContentView from ProfileManager. Backend uses this for isolated memory.
    /// When nil, we send "default" so the backend still works before any profile is added.
    var activeProfileId: UUID?

    /// Speaks AI replies aloud using the system TTS.
    private let speechManager = SpeechManager()

    /// Used to replace the thinking placeholder when the real reply arrives.
    private var lastThinkingPlaceholderText: String?
    /// When to show the reply (so we never respond instantly; calmer for kids).
    private var thinkingEndTime: Date?

    /// Friendly phrases shown while waiting. Random choice feels more natural.
    private static let thinkingPhrases = [
        "Let me think...",
        "Hmm...",
        "That's a good question!"
    ]

    init() {
        speechManager.onDidFinishSpeaking = { [weak self] in
            DispatchQueue.main.async { self?.conversationState = .idle }
        }
    }

    /// Called by the view when the mic starts or stops (so we can show "Listening...").
    func setConversationState(_ state: ConversationState) {
        conversationState = state
    }

    // MARK: - Sending messages

    /// Sends the current input to the backend and appends the reply (or an error message).
    func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isLoading else { return }

        // 1. Append user message and clear input
        let userMessage = ChatMessage(id: UUID(), text: text, isUser: true)
        messages.append(userMessage)
        inputText = ""
        isLoading = true

        // 2. Show thinking state: placeholder message + minimum delay so it never feels instant
        conversationState = .thinking
        let phrase = ChatViewModel.thinkingPhrases.randomElement() ?? "Let me think..."
        lastThinkingPlaceholderText = phrase
        thinkingEndTime = Date().addingTimeInterval(Double.random(in: 0.8...1.2))
        messages.append(ChatMessage(id: UUID(), text: phrase, isUser: false))

        // 3. Send POST request and handle response on main thread
        Task {
            await performRequest(userMessageText: text)
        }
    }

    /// Performs the HTTP POST and updates messages when done.
    @MainActor
    private func performRequest(userMessageText: String) async {
        defer { isLoading = false }

        guard let url = URL(string: ChatViewModel.SERVER_URL) else {
            replacePlaceholderAndShowError("Connection error. Please try again.")
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let profileIdString = activeProfileId?.uuidString ?? "default"
        request.httpBody = try? JSONEncoder().encode(ChatRequest(message: userMessageText, profile_id: profileIdString))

        do {
            let (data, response) = try await URLSession.shared.data(for: request)

            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                replacePlaceholderAndShowError("Connection error. Please try again.")
                return
            }

            let decoded = try? JSONDecoder().decode(ChatResponse.self, from: data)
            let replyText = decoded?.reply ?? "No reply from server."
            replacePlaceholderAndShowReply(replyText)
        } catch {
            replacePlaceholderAndShowError("Connection error. Please try again.")
        }
    }

    /// After the thinking delay, replace the placeholder with the real reply and speak.
    private func replacePlaceholderAndShowReply(_ replyText: String) {
        guard let endTime = thinkingEndTime else {
            let aiMessage = ChatMessage(id: UUID(), text: replyText, isUser: false)
            messages.append(aiMessage)
            conversationState = .speaking
            speechManager.speak(replyText)
            return
        }
        let delay = max(0, endTime.timeIntervalSinceNow)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.removeThinkingPlaceholderIfNeeded()
            let aiMessage = ChatMessage(id: UUID(), text: replyText, isUser: false)
            self?.messages.append(aiMessage)
            self?.conversationState = .speaking
            self?.speechManager.speak(replyText)
            self?.lastThinkingPlaceholderText = nil
            self?.thinkingEndTime = nil
        }
    }

    /// After the thinking delay, replace the placeholder with an error message and speak it.
    private func replacePlaceholderAndShowError(_ errorText: String) {
        guard let endTime = thinkingEndTime else {
            let errorMessage = ChatMessage(id: UUID(), text: errorText, isUser: false)
            messages.append(errorMessage)
            conversationState = .speaking
            speechManager.speak(errorText)
            return
        }
        let delay = max(0, endTime.timeIntervalSinceNow)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.removeThinkingPlaceholderIfNeeded()
            let errorMessage = ChatMessage(id: UUID(), text: errorText, isUser: false)
            self?.messages.append(errorMessage)
            self?.conversationState = .speaking
            self?.speechManager.speak(errorText)
            self?.lastThinkingPlaceholderText = nil
            self?.thinkingEndTime = nil
        }
    }

    private func removeThinkingPlaceholderIfNeeded() {
        if let placeholder = lastThinkingPlaceholderText, messages.last?.text == placeholder {
            messages.removeLast()
        }
    }
}
