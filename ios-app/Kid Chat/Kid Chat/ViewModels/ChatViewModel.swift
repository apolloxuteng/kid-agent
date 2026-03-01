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

/// Response body we get back from the backend (non-streaming /chat).
/// When the user asked for an image and one was found, imageBase64 and imageMediaType are set.
private struct ChatResponse: Decodable {
    let reply: String
    let imageBase64: String?
    let imageMediaType: String?

    enum CodingKeys: String, CodingKey {
        case reply
        case imageBase64 = "image_base64"
        case imageMediaType = "image_media_type"
    }
}

/// SSE event from POST /chat/stream: token, progress (e.g. "Finding a picture..."), done with reply, or error.
/// When done includes an image (e.g. Pixabay), imageBase64 and imageMediaType are set.
private struct StreamEvent: Decodable {
    var token: String?
    var progress: String?
    var done: Bool?
    var reply: String?
    var error: String?
    var imageBase64: String?
    var imageMediaType: String?

    enum CodingKeys: String, CodingKey {
        case token, progress, done, reply, error
        case imageBase64 = "image_base64"
        case imageMediaType = "image_media_type"
    }
}

/// Connects the UI to the chat backend: stores messages, handles send, updates UI.
class ChatViewModel: ObservableObject {

    // MARK: - Configuration
    /// Server base URL. Read from Info.plist key "ServerBaseURL" if set; otherwise default. Run backend: uvicorn server:app --host 0.0.0.0
    static var SERVER_BASE: String {
        (Bundle.main.infoDictionary?["ServerBaseURL"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? "http://192.168.68.71:8000"
    }
    /// Streaming endpoint: same body as /chat, returns SSE (token / done / error).
    static var streamURL: URL? { URL(string: SERVER_BASE + "/chat/stream") }
    /// Non-streaming fallback when streaming fails.
    static var chatURL: URL? { URL(string: SERVER_BASE + "/chat") }
    /// Health check for connection retry (GET /health).
    static var healthURL: URL? { URL(string: SERVER_BASE + "/health") }
    /// Keep only the last N messages to bound memory in long sessions.
    private static let maxMessages = 100
    /// Request timeout so we don't stay in .thinking forever if the server hangs. Tool-calling (e.g. space/joke) can take 30–60+ seconds.
    private static let requestTimeoutSeconds: UInt64 = 120
    /// Interval between connection retries when server was unreachable.
    private static let retryIntervalSeconds: UInt64 = 15

    // MARK: - Published state (SwiftUI observes these and redraws when they change)

    /// All messages in the conversation (user and AI).
    @Published var messages: [ChatMessage] = []

    /// Current text in the input field.
    @Published var inputText: String = ""

    /// True while we’re waiting for the backend reply (used to disable Send and show loading).
    @Published var isLoading: Bool = false

    /// Drives status text and button states (listening / thinking / speaking). Single source of truth for conversation state.
    @Published var conversationState: ConversationState = .idle

    /// Status string for the current state (header, accessibility). Derived from conversationState.
    var statusText: String { ConversationState.statusText(for: conversationState) }

    /// Active child profile id; set by ContentView from ProfileManager. Backend uses this for isolated memory.
    /// When nil, we send "default" so the backend still works before any profile is added.
    var activeProfileId: UUID?

    /// Speaks AI replies aloud using the system TTS.
    private let speechManager = SpeechManager()

    /// Used to replace the thinking placeholder when the real reply arrives.
    private var lastThinkingPlaceholderText: String?
    /// When to show the reply (so we never respond instantly; calmer for kids).
    private var thinkingEndTime: Date?
    /// ID of the current streaming AI message so we can update it in place.
    private var streamingMessageId: UUID?
    /// In-flight request task; cancelled when user leaves chat or profile changes.
    private var currentRequestTask: Task<Void, Never>?
    /// Timeout task: cancels the request and resets state if the request runs too long.
    private var requestTimeoutTask: Task<Void, Never>?
    /// Retry task: periodically pings server when connection was lost; cancelled when server is reachable again.
    private var connectionRetryTask: Task<Void, Never>?

    /// Fun placeholder phrases while waiting for the reply (works for any message, not just questions).
    private static let thinkingPhrases = [
        "Ooh, let me think...",
        "Hang on a sec...",
        "Thinking really hard...",
        "One moment...",
        "So many ideas...",
        "Almost there...",
        "Let me figure that out...",
        "Ooh, I'm thinking...",
    ]

    init() {
        speechManager.onDidFinishSpeaking = { [weak self] in
            Task { @MainActor in
                // Only clear to idle if we're still in speaking; if user interrupted and started talking (.listening), keep mic red until they're done.
                if self?.conversationState == .speaking {
                    self?.conversationState = .idle
                }
            }
        }
    }

    /// Called by the view when the mic starts or stops (so we can show "Listening...").
    func setConversationState(_ state: ConversationState) {
        conversationState = state
    }

    /// Stops TTS immediately. Call when the user taps the mic during speaking to cut off long replies.
    func stopSpeaking() {
        speechManager.stop()
        conversationState = .idle
    }

    /// Cancels any in-flight request and stops TTS. Call when the user leaves the chat (e.g. view disappears or profile switches).
    func cancelRequest() {
        currentRequestTask?.cancel()
        currentRequestTask = nil
        speechManager.stop()
        if isLoading { isLoading = false }
        if conversationState == .thinking || conversationState == .speaking { conversationState = .idle }
    }

    /// Applies conversation settings to TTS. Call when the settings sheet appears or when voice/mute changes.
    func updateVoiceAndMute(voiceIdentifier: String?, muted: Bool) {
        speechManager.isMuted = muted
        speechManager.setSelectedVoice(identifier: voiceIdentifier)
        if muted {
            speechManager.stop()
            if conversationState == .speaking { conversationState = .idle }
        }
    }

    // MARK: - Sending messages

    /// Sends the current input to the backend and appends the reply (or an error message).
    func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isLoading else { return }

        // 1. Append user message and clear input
        let userMessage = ChatMessage(id: UUID(), text: text, isUser: true)
        messages.append(userMessage)
        trimMessagesIfNeeded()
        inputText = ""
        isLoading = true

        // 2. Show thinking state: placeholder message + minimum delay so it never feels instant
        conversationState = .thinking
        let phrase = ChatViewModel.thinkingPhrases.randomElement() ?? "Ooh, let me think..."
        lastThinkingPlaceholderText = phrase
        thinkingEndTime = Date().addingTimeInterval(Double.random(in: 0.3...0.5))
        let placeholderId = UUID()
        streamingMessageId = placeholderId
        messages.append(ChatMessage(id: placeholderId, text: phrase, isUser: false))
        trimMessagesIfNeeded()

        // 3. Send POST to streaming endpoint and consume SSE
        currentRequestTask = Task {
            await performStreamingRequest(userMessageText: text, placeholderId: placeholderId)
            currentRequestTask = nil
        }
    }

    /// Performs POST /chat/stream, consumes SSE, and updates the placeholder message as tokens arrive.
    @MainActor
    private func performStreamingRequest(userMessageText: String, placeholderId: UUID) async {
        requestTimeoutTask?.cancel()
        requestTimeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.requestTimeoutSeconds * 1_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                guard let self else { return }
                if self.isLoading {
                    self.currentRequestTask?.cancel()
                    self.requestTimeoutTask = nil
                    self.isLoading = false
                    if self.conversationState == .thinking { self.conversationState = .idle }
                    self.replacePlaceholderAndShowError("Request timed out. Check that the server is running at \(ChatViewModel.SERVER_BASE).", connectionLost: true)
                }
            }
        }
        defer {
            requestTimeoutTask?.cancel()
            requestTimeoutTask = nil
            isLoading = false
            streamingMessageId = nil
        }

        if Task.isCancelled { return }

        guard let url = ChatViewModel.streamURL else {
            replacePlaceholderAndShowError("Connection error. Please try again.", connectionLost: true)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 150
        let profileIdString = activeProfileId?.uuidString ?? "default"
        request.httpBody = try? JSONEncoder().encode(ChatRequest(message: userMessageText, profile_id: profileIdString))

        do {
            let (bytes, response) = try await URLSession.shared.bytes(for: request)

            guard let http = response as? HTTPURLResponse else {
                replacePlaceholderAndShowError("Connection error. Please try again.", connectionLost: true)
                return
            }
            guard http.statusCode == 200 else {
                let msg = "Server error (\(http.statusCode)). Check that the backend is running at \(ChatViewModel.SERVER_BASE)."
                replacePlaceholderAndShowError(msg, connectionLost: true)
                return
            }

            var accumulated = ""
            var lastSpokenLength = 0
            var hasStartedSpeaking = false
            var lineBuffer: [UInt8] = []
            for try await byte in bytes {
                if Task.isCancelled {
                    removeThinkingPlaceholderIfNeeded()
                    if let idx = messages.lastIndex(where: { $0.id == placeholderId }) { messages.remove(at: idx) }
                    return
                }
                lineBuffer.append(byte)
                if byte != 0x0A { continue }
                guard let line = String(bytes: lineBuffer, encoding: .utf8) else { lineBuffer = []; continue }
                lineBuffer = []

                guard line.hasPrefix("data: ") else { continue }
                let jsonStr = line.dropFirst(6).trimmingCharacters(in: .whitespacesAndNewlines)
                guard !jsonStr.isEmpty, let data = jsonStr.data(using: .utf8) else { continue }

                let event = try? JSONDecoder().decode(StreamEvent.self, from: data)

                if let token = event?.token, !token.isEmpty {
                    accumulated += token
                    updateStreamingMessage(placeholderId: placeholderId, text: accumulated)
                    if let (chunk, newEnd) = nextSpeakableChunk(accumulated, from: lastSpokenLength) {
                        speechManager.enqueueMore(chunk)
                        lastSpokenLength = newEnd
                        if !hasStartedSpeaking {
                            hasStartedSpeaking = true
                            if !speechManager.isMuted { conversationState = .speaking }
                        }
                    }
                } else if let progress = event?.progress, !progress.isEmpty {
                    updateStreamingMessage(placeholderId: placeholderId, text: progress)
                } else if event?.done == true, let reply = event?.reply {
                    // TTS remainder: what we haven't spoken from the stream, plus any tail the server sent only in done (e.g. Knowledge mode)
                    let remainderFromStream = accumulated.dropFirst(lastSpokenLength)
                    if !remainderFromStream.isEmpty { speechManager.enqueueMore(String(remainderFromStream)) }
                    if reply.count > accumulated.count {
                        let extraFromReply = reply.dropFirst(accumulated.count)
                        if !extraFromReply.isEmpty { speechManager.enqueueMore(String(extraFromReply)) }
                    }
                    if !hasStartedSpeaking && !speechManager.isMuted {
                        conversationState = .speaking
                        // Fallback: if we enqueued nothing (no remainder, no extra), speak the full reply so voice still plays
                        let hadNothingToEnqueue = remainderFromStream.isEmpty && reply.count <= accumulated.count
                        if !reply.isEmpty && hadNothingToEnqueue { speechManager.speak(reply) }
                    }
                    let imageData = event?.imageBase64.flatMap { Data(base64Encoded: $0) }
                    let imageMediaType = event?.imageMediaType
                    replacePlaceholderWithFinalReply(placeholderId: placeholderId, replyText: reply, imageData: imageData, imageMediaType: imageMediaType, speak: false)
                    return
                } else if let errorMsg = event?.error, !errorMsg.isEmpty {
                    replacePlaceholderAndShowError(errorMsg, connectionLost: false)
                    return
                }
            }
            // Stream ended without done/error; use accumulated if any
            if !accumulated.isEmpty {
                let remainder = accumulated.dropFirst(lastSpokenLength)
                if !remainder.isEmpty { speechManager.enqueueMore(String(remainder)) }
                if !hasStartedSpeaking && !speechManager.isMuted { conversationState = .speaking }
                replacePlaceholderWithFinalReply(placeholderId: placeholderId, replyText: accumulated, speak: false)
            } else {
                replacePlaceholderAndShowError("No reply from server.", connectionLost: true)
            }
        } catch {
            await fallbackToNonStreaming(userMessageText: userMessageText, placeholderId: placeholderId, streamError: error)
        }
    }

    /// On streaming failure, try once with POST /chat (non-streaming) so the app still works.
    @MainActor
    private func fallbackToNonStreaming(userMessageText: String, placeholderId: UUID, streamError: Error) async {
        guard let url = ChatViewModel.chatURL else {
            replacePlaceholderAndShowError(connectionErrorMessage(for: streamError), connectionLost: true)
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 150
        let profileIdString = activeProfileId?.uuidString ?? "default"
        request.httpBody = try? JSONEncoder().encode(ChatRequest(message: userMessageText, profile_id: profileIdString))

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                replacePlaceholderAndShowError("Server error. Check \(ChatViewModel.SERVER_BASE) and try again.", connectionLost: true)
                return
            }
            let decoded = try? JSONDecoder().decode(ChatResponse.self, from: data)
            let replyText = decoded?.reply ?? "No reply from server."
            let imageData = decoded?.imageBase64.flatMap { Data(base64Encoded: $0) }
            let imageMediaType = decoded?.imageMediaType
            replacePlaceholderWithFinalReply(placeholderId: placeholderId, replyText: replyText, imageData: imageData, imageMediaType: imageMediaType)
        } catch {
            replacePlaceholderAndShowError(connectionErrorMessage(for: streamError), connectionLost: true)
        }
    }

    /// User-facing message for network/stream errors.
    private func connectionErrorMessage(for error: Error) -> String {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost:
                return "Cannot reach the server. Is it running at \(ChatViewModel.SERVER_BASE)? Same Wi‑Fi?"
            case NSURLErrorTimedOut:
                return "Request timed out. Try again."
            case NSURLErrorNotConnectedToInternet:
                return "No internet connection."
            default:
                break
            }
        }
        return "Connection error: \(error.localizedDescription)"
    }

    /// Returns true if the server responds to GET /health with 200. Used for retry-after-disconnect.
    func checkServerReachability() async -> Bool {
        guard let url = ChatViewModel.healthURL else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 8
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return false }
            return true
        } catch {
            return false
        }
    }

    /// Call when connection error was shown: start periodic retry. When server is reachable again, reset state so mic is available.
    private func startConnectionRetryLoop() {
        connectionRetryTask?.cancel()
        connectionRetryTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: Self.retryIntervalSeconds * 1_000_000_000)
                if Task.isCancelled { break }
                guard let self else { return }
                let reachable = await self.checkServerReachability()
                if reachable {
                    await MainActor.run {
                        self.connectionRetryTask?.cancel()
                        self.connectionRetryTask = nil
                        self.isLoading = false
                        if self.conversationState == .thinking {
                            self.conversationState = .idle
                        }
                    }
                    break
                }
            }
        }
    }

    /// Returns the next chunk of text that ends in a sentence boundary (. ! ?), and the end index.
    /// We use only sentence boundaries (not comma) so TTS gets full sentences and we avoid splitting on phrases like "a country, a famous person".
    private func nextSpeakableChunk(_ full: String, from startIndex: Int) -> (String, Int)? {
        let after = full.dropFirst(startIndex)
        guard !after.isEmpty else { return nil }
        let boundaries: [Character] = [".", "!", "?"]
        var lastOffset: Int?
        for b in boundaries {
            if let i = after.lastIndex(of: b) {
                let o = after.distance(from: after.startIndex, to: i)
                if lastOffset == nil || o > lastOffset! { lastOffset = o }
            }
        }
        guard let idx = lastOffset else { return nil }
        let chunk = String(after.prefix(idx + 1))
        let newEnd = startIndex + idx + 1
        return (chunk, newEnd)
    }

    /// Replaces the streaming placeholder message with updated text (for token-by-token UI).
    private func updateStreamingMessage(placeholderId: UUID, text: String) {
        guard let idx = messages.lastIndex(where: { $0.id == placeholderId }) else { return }
        messages[idx] = ChatMessage(id: placeholderId, text: text, isUser: false)
    }

    /// Replaces the streaming placeholder with the final reply. If speak is true, speaks the full reply (e.g. non-streaming fallback).
    /// When imageData/imageMediaType are provided (e.g. from Pixabay), the message is shown with the image in the bubble.
    private func replacePlaceholderWithFinalReply(placeholderId: UUID, replyText: String, imageData: Data? = nil, imageMediaType: String? = nil, speak: Bool = true) {
        removeThinkingPlaceholderIfNeeded()
        let finalMessage = ChatMessage(id: placeholderId, text: replyText, isUser: false, imageData: imageData, imageMediaType: imageMediaType)
        guard let idx = messages.lastIndex(where: { $0.id == placeholderId }) else {
            messages.append(finalMessage)
            trimMessagesIfNeeded()
            if !speechManager.isMuted {
                conversationState = .speaking
            } else {
                conversationState = .idle
            }
            if speak { speechManager.speak(replyText) }
            lastThinkingPlaceholderText = nil
            thinkingEndTime = nil
            return
        }
        messages[idx] = finalMessage
        if !speechManager.isMuted {
            conversationState = .speaking
        } else {
            conversationState = .idle
        }
        if speak { speechManager.speak(replyText) }
        lastThinkingPlaceholderText = nil
        thinkingEndTime = nil
    }

    /// After the thinking delay, replace the placeholder with an error message and speak it.
    /// When connectionLost is true, starts a periodic retry loop; when server is reachable again, resets state so the mic is available.
    private func replacePlaceholderAndShowError(_ errorText: String, connectionLost: Bool = false) {
        isLoading = false
        guard let endTime = thinkingEndTime else {
            let errorMessage = ChatMessage(id: UUID(), text: errorText, isUser: false)
            messages.append(errorMessage)
            trimMessagesIfNeeded()
            if conversationState == .thinking { conversationState = .idle }
            if !speechManager.isMuted { conversationState = .speaking }
            speechManager.speak(errorText)
            if connectionLost { startConnectionRetryLoop() }
            return
        }
        let delay = max(0, endTime.timeIntervalSinceNow)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self else { return }
            self.isLoading = false
            self.removeThinkingPlaceholderIfNeeded()
            let errorMessage = ChatMessage(id: UUID(), text: errorText, isUser: false)
            self.messages.append(errorMessage)
            self.trimMessagesIfNeeded()
            if self.conversationState == .thinking { self.conversationState = .idle }
            if !self.speechManager.isMuted { self.conversationState = .speaking }
            self.speechManager.speak(errorText)
            self.lastThinkingPlaceholderText = nil
            self.thinkingEndTime = nil
            if connectionLost { self.startConnectionRetryLoop() }
        }
    }

    private func removeThinkingPlaceholderIfNeeded() {
        if let placeholder = lastThinkingPlaceholderText, messages.last?.text == placeholder {
            messages.removeLast()
        }
    }

    /// Keeps only the last maxMessages to bound memory in long sessions.
    private func trimMessagesIfNeeded() {
        if messages.count > Self.maxMessages {
            messages = Array(messages.suffix(Self.maxMessages))
        }
    }
}
