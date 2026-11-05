import AVFoundation
import Foundation
import Speech

/// Push-to-talk dictation for lead notes. Only runs while the rep is holding
/// the record button / has tapped Start; nothing is recorded continuously and
/// no audio file is saved. Recognition stays on-device when the phone supports it.
@MainActor
final class SpeechDictationService: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var transcript = ""
    @Published private(set) var errorMessage: String?
    @Published private(set) var isOnDevice = false

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-CA")) ?? SFSpeechRecognizer()
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var committed = ""

    func requestPermissions() async -> Bool {
        let speech = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { cont.resume(returning: $0 == .authorized) }
        }
        guard speech else {
            errorMessage = "Speech recognition is turned off for Smart Knock in Settings."
            return false
        }
        let mic = await AVAudioApplication.requestRecordPermission()
        if !mic { errorMessage = "Microphone access is turned off for Smart Knock in Settings." }
        return mic
    }

    /// Starts dictation, appending to `existing` text.
    func start(appendingTo existing: String) async {
        guard !isRecording else { return }
        errorMessage = nil
        guard await requestPermissions() else { return }
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Speech recognition is not available right now."
            return
        }
        committed = existing.trimmingCharacters(in: .whitespacesAndNewlines)
        transcript = committed

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            req.addsPunctuation = true
            req.taskHint = .dictation
            if recognizer.supportsOnDeviceRecognition {
                req.requiresOnDeviceRecognition = true
                isOnDevice = true
            } else {
                isOnDevice = false
            }
            request = req

            let input = audioEngine.inputNode
            let format = input.outputFormat(forBus: 0)
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                req.append(buffer)
            }
            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true

            task = recognizer.recognitionTask(with: req) { [weak self] result, error in
                let text = result?.bestTranscription.formattedString
                let final = result?.isFinal ?? false
                Task { @MainActor in
                    guard let self else { return }
                    if let text {
                        self.transcript = self.committed.isEmpty ? text : self.committed + " " + text
                    }
                    if error != nil || final { self.finish() }
                }
            }
        } catch {
            errorMessage = "Could not start the microphone: \(error.localizedDescription)"
            finish()
        }
    }

    /// Stops listening. The recognizer then delivers its final text and cleans up.
    func stop() {
        stopAudio()
        request?.endAudio()
        isRecording = false
        // Safety net in case the recognizer never sends a final result.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if self.task != nil && !self.isRecording { self.finish() }
        }
    }

    private func stopAudio() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
    }

    private func finish() {
        stopAudio()
        task?.cancel()
        task = nil
        request = nil
        isRecording = false
        committed = transcript
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
