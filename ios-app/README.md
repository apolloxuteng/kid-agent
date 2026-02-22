# Kid Chat (iOS)

Minimal SwiftUI chat app that talks to the kid-agent backend over your local network. **Step 1** of a larger conversational app.

## Requirements

- Xcode 15+
- iOS 17+ deployment target
- Backend running at `http://<YOUR_IP>:8000` (see Configuration below)

## Create the project in Xcode

1. **New project:** File → New → Project → **App**.
   - Product Name: **Kid Chat**
   - Interface: **SwiftUI**
   - Language: **Swift**
   - Minimum Deployments: **iOS 17.0**
   - Uncheck "Include Tests" if you want to keep it minimal.

2. **Add the app files:** Drag these Swift files from this folder into the Xcode project (under the Kid Chat group), and when asked, choose **Copy items if needed** and add to the Kid Chat target:
   - `KidChatApp.swift` (replace the default one Xcode created)
   - `ContentView.swift` (replace the default one)
   - `ChatMessage.swift`
   - `ChatViewModel.swift`
   - `SpeechRecognizer.swift` (for voice input)
   - `SpeechManager.swift` (for speaking AI replies aloud)

   **Speech permissions:** The app needs microphone and speech recognition for the mic button. Add these to your target’s **Info** (or **Info.plist**):  
   - **NSMicrophoneUsageDescription** — e.g. “Kid Chat uses the microphone so you can speak your message instead of typing.”  
   - **NSSpeechRecognitionUsageDescription** — e.g. “Kid Chat converts your voice into text so you can send a message by talking.”  
   You can copy the keys and strings from the provided `Info.plist` in this folder, or add that file to your target if you don’t have one.

3. **Allow HTTP for your backend:** iOS blocks plain `http://` by default.
   - In the **left sidebar**, click the **blue project icon** at the top (your project name, e.g. "Kid Chat").
   - In the middle column, under **TARGETS**, select **Kid Chat** (the app target, not the project).
   - At the top of the right-hand area, click the **Info** tab (next to General, Signing & Capabilities).
   - In the **Custom iOS Target Properties** table, click the **+** button to add a row (or right‑click → Add Row).
   - Type **App Transport** and pick **App Transport Security Settings** (Dictionary). Expand it with the disclosure triangle.
   - Click the **+** next to "App Transport Security Settings" and add **Allow Arbitrary Loads** (Boolean) = **YES**.

4. **Set the server URL:** In `ChatViewModel.swift`, set `SERVER_BASE` to your Mac’s IP and port, e.g.:
   ```swift
   static let SERVER_BASE = "http://192.168.1.100:8000"
   ```
   The app uses the streaming endpoint `/chat/stream`. Find your Mac’s IP: **System Settings → Network → Wi‑Fi → Details** (or run `ifconfig | grep "inet "` in Terminal).

5. **Run:** Choose a simulator or a device and press Run. Make sure the backend is running (`uvicorn server:app` in `kid-agent/backend`) and that the phone/simulator can reach that IP.

## Configuration

- **SERVER_BASE** in `ChatViewModel.swift`: change the host to your Mac Mini (or dev Mac) IP so the app can reach the backend. The app calls `SERVER_BASE + "/chat/stream"` for streaming replies. The backend must be running (e.g. `uvicorn server:app` in `kid-agent/backend`).

## File roles

| File              | Role                                                                 |
|-------------------|----------------------------------------------------------------------|
| `KidChatApp.swift`| App entry point; creates the window with `ContentView`.             |
| `ContentView.swift` | Chat UI: title, message list, input bar, mic button, Send button. |
| `ChatViewModel.swift` | State and networking: messages, input text, `sendMessage()`.    |
| `ChatMessage.swift`  | Data model for one message (id, text, isUser).                   |
| `SpeechRecognizer.swift` | Voice input: requests permissions, records with AVAudioEngine, converts speech to text with Speech.framework. |
| `SpeechManager.swift` | Text-to-speech: uses AVSpeechSynthesizer to speak AI replies aloud (child-friendly rate and volume). |

## Quick test

1. Start backend: `cd kid-agent/backend && source venv/bin/activate && uvicorn server:app --reload --host 0.0.0.0` (use `--host 0.0.0.0` so the phone can reach it).
2. Set `SERVER_BASE` in `ChatViewModel.swift` to your Mac’s IP.
3. Run the app and send a message.

---

## How it works (beginner-friendly)

**How SwiftUI updates the UI automatically**  
The view (e.g. `ContentView`) uses `@StateObject` and `@Published` so it “observes” the ViewModel. When the ViewModel changes something like `messages` or `inputText`, SwiftUI sees that and redraws only the parts of the screen that depend on that data. You don’t call “refresh” yourself; SwiftUI does it when the observed data changes.

**How the ViewModel connects UI and network**  
The ViewModel holds the data (`messages`, `inputText`) and the action (`sendMessage()`). When the user taps Send, the view calls `viewModel.sendMessage()`. The ViewModel adds the user message to the list, clears the field, then does the HTTP request. When the reply (or error) comes back, it updates `messages` again. Because the view observes the ViewModel, the new message (or “...” and then the reply) appears on screen automatically.

**Speech-to-text (mic button)**  
Tapping the mic uses `SpeechRecognizer` (Speech + AVFoundation). It requests permission, then records and streams audio to `SFSpeechAudioBufferRecognitionRequest`; partial results go to `transcript`, and the view copies that into `viewModel.inputText` so the text field shows live transcription. Recognition runs on the device (or Apple’s servers if needed); no audio goes to your backend. Sending still happens only when the user taps Send; voice only fills the input field.

**Text-to-speech (AI replies)**  
When the backend returns a reply, `ChatViewModel` appends it to the chat and calls `SpeechManager.speak(reply)`. `SpeechManager` uses `AVSpeechSynthesizer`: it builds an `AVSpeechUtterance` with the text, sets a slightly slower rate and moderate volume for a child, and the system speaks it on the device. No audio is sent to any server; synthesis is local. If a new reply arrives while the previous one is still playing, the current speech is stopped and the new reply is spoken.