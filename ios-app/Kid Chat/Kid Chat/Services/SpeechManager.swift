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
    /// All access must happen on the main queue to avoid races with the synthesizer delegate.
    private var sentenceQueue: [AVSpeechUtterance] = []
    /// Called when all sentences have finished (so UI can set conversationState = .idle).
    var onDidFinishSpeaking: (() -> Void)?

    /// When true, speak and enqueueMore do nothing; keeps state consistent (stops and clears queue when muting).
    var isMuted: Bool = false
    /// When set, used for all new utterances; nil means use preferredVoice().
    var selectedVoice: AVSpeechSynthesisVoice?

    /// Sets the voice by identifier. Pass nil to use the default preferred voice.
    func setSelectedVoice(identifier: String?) {
        if let id = identifier, !id.isEmpty {
            selectedVoice = AVSpeechSynthesisVoice(identifier: id)
        } else {
            selectedVoice = nil
        }
    }

    override init() {
        synthesizer = AVSpeechSynthesizer()
        super.init()
        synthesizer.delegate = self
    }

    /// Speaks the given text. Splits into sentences and speaks them sequentially
    /// with emotional variation. Stops any current speech first.
    /// Emojis and punctuation are stripped before speaking so TTS doesn't read them aloud.
    func speak(_ text: String) {
        dispatchToMainIfNeeded {
            self._speak(text)
        }
    }

    private func _speak(_ text: String) {
        if isMuted {
            synthesizer.stopSpeaking(at: .immediate)
            sentenceQueue.removeAll()
            return
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        ensureAudioSession()

        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        sentenceQueue.removeAll()

        let textNoEmoji = stripEmojis(trimmed)
        let sentences = splitIntoSentences(textNoEmoji)
        sentenceQueue = sentences.compactMap { s -> AVSpeechUtterance? in
            let u = utterance(for: s)
            guard !u.speechString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return u
        }

        startNextInQueueIfNeeded()
    }

    /// Appends more text to the speech queue and starts speaking if not already.
    /// Use this during streaming so voice can start before the full message arrives.
    /// All queue access is serialized on the main queue to prevent skip/duplicate from delegate races.
    func enqueueMore(_ text: String) {
        dispatchToMainIfNeeded {
            self._enqueueMore(text)
        }
    }

    private func _enqueueMore(_ text: String) {
        if isMuted { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        ensureAudioSession()

        let textNoEmoji = stripEmojis(trimmed)
        let sentences = splitIntoSentences(textNoEmoji)
        for s in sentences {
            let u = utterance(for: s)
            // Skip empty utterances so the synthesizer doesn't get stuck (no didFinish) and leave mic purple
            guard !u.speechString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
            sentenceQueue.append(u)
        }
        startNextInQueueIfNeeded()
    }

    /// Run the block on the main queue. If already on main, run synchronously to keep ordering.
    private func dispatchToMainIfNeeded(_ block: @escaping () -> Void) {
        if Thread.isMainThread {
            block()
        } else {
            DispatchQueue.main.async(execute: block)
        }
    }

    private func ensureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        do {
            // .defaultToSpeaker is only valid with .playAndRecord; for .playback the default is already speaker.
            try session.setCategory(.playback, mode: .default, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch { }
    }

    /// Must be called on the main queue only. Starts the next queued utterance or notifies that we're done.
    /// Skips empty utterances so we never get stuck with the synthesizer not calling didFinish.
    /// - Parameter continuingAfterFinish: When true (from delegate), we don't check isSpeaking so we always advance; the synthesizer can still report isSpeaking briefly after didFinish and would otherwise block the next utterance and onDidFinishSpeaking.
    private func startNextInQueueIfNeeded(continuingAfterFinish: Bool = false) {
        if !continuingAfterFinish && synthesizer.isSpeaking { return }
        while let next = sentenceQueue.first {
            sentenceQueue.removeFirst()
            let text = next.speechString.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            synthesizer.speak(next)
            return
        }
        onDidFinishSpeaking?()
    }

    /// Stops playback immediately. Safe to call from any thread.
    func stop() {
        if Thread.isMainThread {
            _stop()
        } else {
            DispatchQueue.main.async { [weak self] in self?._stop() }
        }
    }

    private func _stop() {
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
        if results.isEmpty {
            return text.trimmingCharacters(in: .whitespaces).isEmpty ? [] : [text]
        }
        return results
    }

    // MARK: - Utterance configuration

    /// Builds an AVSpeechUtterance for one sentence with rate/pitch/voice.
    /// Applies simple emotional variation: exclamation → higher pitch, question → slightly slower.
    /// Punctuation is stripped from the spoken string so TTS doesn't read it aloud.
    private func utterance(for sentence: String) -> AVSpeechUtterance {
        let spokenText = stripPunctuation(sentence)
        let utterance = AVSpeechUtterance(string: spokenText.isEmpty ? sentence : spokenText)
        utterance.voice = selectedVoice ?? preferredVoice()
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

    /// Called on a background thread by AVSpeechSynthesizer. We dispatch to main so all queue access is serialized.
    /// We pass continuingAfterFinish: true so we always run the next or call onDidFinishSpeaking; the synthesizer can still report isSpeaking briefly and would otherwise leave the mic stuck purple.
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        DispatchQueue.main.async { [weak self] in
            self?.startNextInQueueIfNeeded(continuingAfterFinish: true)
        }
    }
}
