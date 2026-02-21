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
    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Configure audio session for playback (needed so iPad/speaker output works after mic use)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            // Continue anyway
        }

        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }

        let sentences = splitIntoSentences(trimmed)
        sentenceQueue = sentences.map { sentence in
            utterance(for: sentence)
        }

        guard let first = sentenceQueue.first else {
            onDidFinishSpeaking?()
            return
        }
        sentenceQueue.removeFirst()
        synthesizer.speak(first)
    }

    /// Stops playback immediately.
    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        sentenceQueue.removeAll()
    }

    // MARK: - Sentence splitting

    /// Splits text into sentences (by . ! ?). Single sentence or no delimiter → one element.
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
    private func utterance(for sentence: String) -> AVSpeechUtterance {
        let utterance = AVSpeechUtterance(string: sentence)
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
