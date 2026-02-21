//
//  SpeechManager.swift
//  Kid Chat
//
//  Uses AVSpeechSynthesizer to speak AI replies aloud. All processing happens
//  on the device; no audio is sent to any server. Notifies when speech finishes
//  so the app can return to idle state.
//

import AVFoundation

/// Speaks text using the system voice. Tuned for clear, child-friendly playback.
final class SpeechManager: NSObject, AVSpeechSynthesizerDelegate {

    private let synthesizer: AVSpeechSynthesizer

    /// Called when the current utterance finishes (so UI can set conversationState = .idle).
    var onDidFinishSpeaking: (() -> Void)?

    override init() {
        synthesizer = AVSpeechSynthesizer()
        super.init()
        synthesizer.delegate = self
    }

    /// Speaks the given text. If something is already playing, it is stopped first.
    /// Uses a slower rate and clear voice so a young child can follow.
    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        // Configure audio session for playback (mic leaves it in .record, so iPad gets no sound without this)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            // Fallback: still try to speak
        }

        // Safety: stop any current speech before starting new one
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }

        let utterance = AVSpeechUtterance(string: trimmed)

        // Slightly slower than default so a 5-year-old can follow
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.85

        // Use system default voice (clear, consistent)
        utterance.voice = AVSpeechSynthesisVoice(language: nil)

        // Volume 0–1; moderate so it’s clear but not loud
        utterance.volume = 0.9

        // Slight pitch variation can help clarity; default is 1.0
        utterance.pitchMultiplier = 1.0

        synthesizer.speak(utterance)
    }

    /// Stops playback immediately.
    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }

    // MARK: - AVSpeechSynthesizerDelegate

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        DispatchQueue.main.async { [weak self] in
            self?.onDidFinishSpeaking?()
        }
    }
}
