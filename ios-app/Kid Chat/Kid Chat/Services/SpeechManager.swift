//
//  SpeechManager.swift
//  Kid Chat
//
//  Uses AVSpeechSynthesizer to speak AI replies aloud. Tuned for warmth and
//  expressiveness for children ages 3–7: slower rate, higher pitch, sentence-
//  by-sentence playback with simple emotional variation (exclamation → higher
//  pitch, question → slightly slower). All processing on device; no audio sent
//  to any server.
//

import AVFoundation

/// Speaks text using the system voice. Configured for warm, expressive,
/// child-friendly playback with sequential sentences and light emotional variation.
final class SpeechManager: NSObject, AVSpeechSynthesizerDelegate {

    private let synthesizer: AVSpeechSynthesizer

    /// Base speaking rate (~0.42). Slower than default so young children can follow.
    private let baseRate: Float = 0.42
    /// Base pitch (~1.18). Slightly higher for a warmer, friendlier tone.
    private let basePitch: Float = 1.18
    /// Slightly slower rate for questions so they feel more inviting.
    private let questionRate: Float = 0.36
    /// Higher pitch for exclamations to sound more expressive.
    private let exclamationPitch: Float = 1.28

    /// Queue of sentences to speak; we speak one at a time and advance in the delegate.
    private var sentenceQueue: [AVSpeechUtterance] = []
    /// Called when all sentences have finished (so UI can set conversationState = .idle).
    var onDidFinishSpeaking: (() -> Void)?

    override init() {
        synthesizer = AVSpeechSynthesizer()
        super.init()
        synthesizer.delegate = self
    }

    /// Speaks the given text. Splits into sentences and speaks them sequentially
    /// with emotional variation. Stops any current speech first.
    /// Emojis and punctuation are stripped before speaking so TTS doesn't read them aloud.
    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        ensureAudioSession()

        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        sentenceQueue.removeAll()

        let textNoEmoji = stripEmojis(trimmed)
        let sentences = splitIntoSentences(textNoEmoji)
        sentenceQueue = sentences.map { utterance(for: $0) }

        startNextInQueueIfNeeded()
    }

    /// Appends more text to the speech queue and starts speaking if not already.
    /// Use this during streaming so voice can start before the full message arrives.
    func enqueueMore(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        ensureAudioSession()

        let textNoEmoji = stripEmojis(trimmed)
        let sentences = splitIntoSentences(textNoEmoji)
        for s in sentences {
            sentenceQueue.append(utterance(for: s))
        }
        startNextInQueueIfNeeded()
    }

    private func ensureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        do {
            // .defaultToSpeaker is only valid with .playAndRecord; for .playback the default is already speaker.
            try session.setCategory(.playback, mode: .default, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch { }
    }

    private func startNextInQueueIfNeeded() {
        guard !sentenceQueue.isEmpty, !synthesizer.isSpeaking else {
            if sentenceQueue.isEmpty { onDidFinishSpeaking?() }
            return
        }
        let next = sentenceQueue.removeFirst()
        synthesizer.speak(next)
    }

    /// Stops playback immediately.
    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        sentenceQueue.removeAll()
    }

    // MARK: - TTS text cleanup (omit emojis and punctuation from being read aloud)

    /// Removes emoji characters (Unicode emoji property) so TTS doesn't read them.
    private func stripEmojis(_ text: String) -> String {
        text.filter { char in
            !char.unicodeScalars.contains { scalar in
                scalar.properties.isEmoji
            }
        }
    }

    /// Removes punctuation and collapses multiple spaces so TTS only speaks words.
    private func stripPunctuation(_ text: String) -> String {
        let withSpaces = text.unicodeScalars
            .map { CharacterSet.punctuationCharacters.contains($0) ? " " : String($0) }
            .joined()
        return withSpaces
            .split(separator: " ", omittingEmptySubsequences: true)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - Sentence splitting

    /// Splits text into sentences (by . ! ?). Single sentence or no delimiter → one element.
    /// Called after stripEmojis so sentences still split correctly; then we strip punctuation per utterance.
    private func splitIntoSentences(_ text: String) -> [String] {
        var results: [String] = []
        var current = ""
        for char in text {
            current.append(char)
            if char == "." || char == "!" || char == "?" {
                let s = current.trimmingCharacters(in: .whitespaces)
                if !s.isEmpty { results.append(s) }
                current = ""
            }
        }
        let remainder = current.trimmingCharacters(in: .whitespaces)
        if !remainder.isEmpty { results.append(remainder) }
        return results.isEmpty ? [text] : results
    }

    // MARK: - Utterance configuration

    /// Builds an AVSpeechUtterance for one sentence with rate/pitch/voice.
    /// Applies simple emotional variation: exclamation → higher pitch, question → slightly slower.
    /// Punctuation is stripped from the spoken string so TTS doesn't read it aloud.
    private func utterance(for sentence: String) -> AVSpeechUtterance {
        let spokenText = stripPunctuation(sentence)
        let utterance = AVSpeechUtterance(string: spokenText.isEmpty ? sentence : spokenText)
        utterance.voice = preferredVoice()
        utterance.volume = 0.9

        let trimmed = sentence.trimmingCharacters(in: .whitespaces)
        if trimmed.hasSuffix("!") {
            utterance.rate = baseRate
            utterance.pitchMultiplier = exclamationPitch
        } else if trimmed.hasSuffix("?") {
            utterance.rate = questionRate
            utterance.pitchMultiplier = basePitch
        } else {
            utterance.rate = baseRate
            utterance.pitchMultiplier = basePitch
        }
        return utterance
    }

    /// Prefers an enhanced-quality English voice when available (iOS 16+), else default English.
    private func preferredVoice() -> AVSpeechSynthesisVoice? {
        if #available(iOS 16.0, *) {
            let enhanced = AVSpeechSynthesisVoice.speechVoices().first { voice in
                voice.quality == .enhanced && (voice.language.hasPrefix("en") || voice.language.hasPrefix("en-"))
            }
            if let enhanced { return enhanced }
        }
        return AVSpeechSynthesisVoice(language: "en-US")
            ?? AVSpeechSynthesisVoice(language: "en-GB")
            ?? AVSpeechSynthesisVoice(language: nil)
    }

    // MARK: - AVSpeechSynthesizerDelegate

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        if let next = sentenceQueue.first {
            sentenceQueue.removeFirst()
            synthesizer.speak(next)
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.onDidFinishSpeaking?()
            }
        }
    }
}
