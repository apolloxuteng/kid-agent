//
//  SpeechRecognizer.swift
//  Kid Chat
//
//  Uses Apple's Speech framework and AVFoundation to convert the user's
//  voice into text. Recording runs on the device; no audio is sent to Apple
//  unless you use on-device recognition (device-dependent).
//

import AVFoundation
import Speech
import SwiftUI

/// Converts speech to text using the microphone. Exposes transcript and recording state
/// so the UI can show live text and a red mic button while recording.
class SpeechRecognizer: NSObject, ObservableObject {

    // MARK: - Published state (UI observes these)

    /// The recognized text so far. Updates live while recording.
    @Published var transcript: String = ""

    /// True while the microphone is active and we are recognizing speech.
    @Published var isRecording: Bool = false

    // MARK: - Private pieces (Speech + AVFoundation)

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    /// After this many seconds with no new speech, we stop recording automatically.
    private let silenceTimeout: TimeInterval = 2.0
    private var silenceWorkItem: DispatchWorkItem?

    override init() {
        super.init()
        speechRecognizer = SFSpeechRecognizer()
    }

    // MARK: - Permissions

    /// Ask the user for speech recognition and microphone access. Call before starting recording.
    /// If permission is denied, we only print a message and do not crash.
    func requestAuthorization(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                switch status {
                case .authorized:
                    completion(true)
                case .denied:
                    print("[SpeechRecognizer] Speech recognition denied. Enable it in Settings → Privacy & Security.")
                    completion(false)
                case .restricted:
                    print("[SpeechRecognizer] Speech recognition is restricted on this device.")
                    completion(false)
                case .notDetermined:
                    print("[SpeechRecognizer] Speech recognition not determined.")
                    completion(false)
                @unknown default:
                    completion(false)
                }
            }
        }
    }

    // MARK: - Recording

    /// Start listening to the microphone and writing recognized text into `transcript`.
    func startRecording() {
        // Reset previous transcript so new speech fills the field
        transcript = ""

        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            print("[SpeechRecognizer] Recognizer not available (e.g. no network for non–on-device recognition).")
            return
        }

        recognitionTask?.cancel()
        recognitionTask = nil

        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("[SpeechRecognizer] Failed to set up audio session: \(error.localizedDescription)")
            return
        }

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else { return }

        recognitionRequest.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            print("[SpeechRecognizer] Could not start audio engine: \(error.localizedDescription)")
            return
        }

        DispatchQueue.main.async { [weak self] in
            self?.isRecording = true
        }

        recognitionTask = recognizer.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            if let error = error {
                // Task was cancelled or failed; don’t treat as fatal
                if (error as NSError).code != 216 && (error as NSError).code != 203 {
                    print("[SpeechRecognizer] Recognition error: \(error.localizedDescription)")
                }
                return
            }

            guard let result = result else { return }

            let newTranscript = result.bestTranscription.formattedString
            DispatchQueue.main.async {
                self?.transcript = newTranscript
                // Reset silence timer: after 2 seconds with no new speech, auto-stop
                self?.scheduleSilenceStop()
            }
        }
    }

    /// Schedules automatic stop when no new speech is heard for `silenceTimeout` seconds.
    private func scheduleSilenceStop() {
        silenceWorkItem?.cancel()
        let item = DispatchWorkItem { [weak self] in
            self?.stopRecording()
        }
        silenceWorkItem = item
        DispatchQueue.main.asyncAfter(deadline: .now() + silenceTimeout, execute: item)
    }

    /// Stop recording and leave the final text in `transcript`.
    func stopRecording() {
        silenceWorkItem?.cancel()
        silenceWorkItem = nil

        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil

        // Release the audio session so TTS (playback) can take over when the reply arrives.
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        DispatchQueue.main.async { [weak self] in
            self?.isRecording = false
        }
    }

    /// Toggle: if recording, stop; otherwise start (after checking permission).
    func toggleRecording() {
        if isRecording {
            stopRecording()
            return
        }

        requestAuthorization { [weak self] authorized in
            guard authorized, let self = self else { return }
            self.startRecording()
        }
    }
}
