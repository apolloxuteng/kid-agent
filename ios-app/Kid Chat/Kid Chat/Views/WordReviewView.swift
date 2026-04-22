//
//  WordReviewView.swift
//  Kid Chat
//
//  Shows vocabulary words taught by the backend and provides a simple shuffled
//  review flow.
//

import SwiftUI

private struct LearnedWordsResponse: Decodable {
    let words: [LearnedWord]
}

private struct LearnedWord: Decodable, Identifiable {
    let word: String
    let meaning: String
    let example: String
    let taughtAt: String

    var id: String { "\(word)-\(taughtAt)" }

    enum CodingKeys: String, CodingKey {
        case word, meaning, example
        case taughtAt = "taught_at"
    }
}

struct WordReviewView: View {
    let profileId: UUID?
    let accentGradient: LinearGradient

    @Environment(\.dismiss) private var dismiss
    @State private var selectedTab: ReviewTab = .list
    @State private var words: [LearnedWord] = []
    @State private var quizWords: [LearnedWord] = []
    @State private var quizIndex = 0
    @State private var showMeaning = false
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ZStack {
                KidTheme.backgroundBottom.ignoresSafeArea()
                VStack(spacing: 16) {
                    Picker("View", selection: $selectedTab) {
                        ForEach(ReviewTab.allCases) { tab in
                            Text(tab.title).tag(tab)
                        }
                    }
                    .pickerStyle(.segmented)
                    .padding(.horizontal)

                    content
                }
                .padding(.top, 12)
            }
            .navigationTitle("Words")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task {
                await loadWords()
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let errorMessage {
            VStack(spacing: 14) {
                Text(errorMessage)
                    .font(.system(size: 17, weight: .medium, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)
                    .multilineTextAlignment(.center)
                Button("Try Again") {
                    Task { await loadWords() }
                }
                .buttonStyle(WordPrimaryButtonStyle(accentGradient: accentGradient))
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if words.isEmpty {
            VStack(spacing: 14) {
                Text("No words yet")
                    .font(.system(size: 24, weight: .bold, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)
                Text("Tap Learn to collect your first word.")
                    .font(.system(size: 17, weight: .medium, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.8))
                    .multilineTextAlignment(.center)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            switch selectedTab {
            case .list:
                wordList
            case .quiz:
                quizView
            }
        }
    }

    private var wordList: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(words) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(item.word.capitalized)
                            .font(.system(size: 24, weight: .bold, design: .rounded))
                            .foregroundStyle(KidTheme.bubbleTextAI)
                        Text(item.meaning)
                            .font(.system(size: 17, weight: .medium, design: .rounded))
                            .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.9))
                        Text(item.example)
                            .font(.system(size: 15, weight: .regular, design: .rounded))
                            .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.75))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
                    .background(Color.white.opacity(0.78))
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .shadow(color: .black.opacity(0.08), radius: 6, x: 0, y: 3)
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
    }

    private var quizView: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 12)

            let current = quizWords[safe: quizIndex] ?? words[0]
            Text("\(quizIndex + 1) of \(quizWords.count)")
                .font(.system(size: 15, weight: .medium, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.7))

            VStack(spacing: 16) {
                Text(current.word.capitalized)
                    .font(.system(size: 38, weight: .bold, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)

                if showMeaning {
                    VStack(spacing: 10) {
                        Text(current.meaning)
                            .font(.system(size: 20, weight: .semibold, design: .rounded))
                            .foregroundStyle(KidTheme.bubbleTextAI)
                            .multilineTextAlignment(.center)
                        Text(current.example)
                            .font(.system(size: 16, weight: .regular, design: .rounded))
                            .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.75))
                            .multilineTextAlignment(.center)
                    }
                } else {
                    Text("Try to remember what it means.")
                        .font(.system(size: 17, weight: .medium, design: .rounded))
                        .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.75))
                        .multilineTextAlignment(.center)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(24)
            .background(Color.white.opacity(0.82))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.1), radius: 8, x: 0, y: 4)
            .padding(.horizontal, 20)

            if showMeaning {
                HStack(spacing: 12) {
                    Button("Again") { nextCard() }
                        .buttonStyle(WordSecondaryButtonStyle())
                    Button("I Knew It") { nextCard() }
                        .buttonStyle(WordPrimaryButtonStyle(accentGradient: accentGradient))
                }
                .padding(.horizontal, 20)
            } else {
                Button("Show Meaning") {
                    withAnimation(.easeOut(duration: 0.2)) {
                        showMeaning = true
                    }
                }
                .buttonStyle(WordPrimaryButtonStyle(accentGradient: accentGradient))
                .padding(.horizontal, 20)
            }

            Button("Shuffle Again") {
                resetQuiz()
            }
            .font(.system(size: 15, weight: .medium, design: .rounded))
            .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.75))
            .padding(.top, 4)

            Spacer(minLength: 20)
        }
    }

    @MainActor
    private func loadWords() async {
        guard let profileId else {
            errorMessage = "Choose a profile first."
            return
        }
        guard let url = URL(string: ChatViewModel.SERVER_BASE + "/words?profile_id=\(profileId.uuidString)&limit=100") else {
            errorMessage = "Cannot open the words list."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                errorMessage = "Could not load words."
                return
            }
            let decoded = try JSONDecoder().decode(LearnedWordsResponse.self, from: data)
            words = decoded.words
            resetQuiz()
        } catch {
            errorMessage = "Could not reach the word list."
        }
    }

    private func resetQuiz() {
        quizWords = words.shuffled()
        quizIndex = 0
        showMeaning = false
    }

    private func nextCard() {
        if quizIndex + 1 >= quizWords.count {
            resetQuiz()
        } else {
            quizIndex += 1
            showMeaning = false
        }
    }
}

private enum ReviewTab: String, CaseIterable, Identifiable {
    case list
    case quiz

    var id: String { rawValue }

    var title: String {
        switch self {
        case .list: return "List"
        case .quiz: return "Quiz"
        }
    }
}

private struct WordPrimaryButtonStyle: ButtonStyle {
    let accentGradient: LinearGradient

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 18, weight: .semibold, design: .rounded))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(accentGradient)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.96 : 1.0)
    }
}

private struct WordSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 18, weight: .semibold, design: .rounded))
            .foregroundStyle(KidTheme.bubbleTextAI)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(Color.white.opacity(0.78))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.96 : 1.0)
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

#Preview {
    WordReviewView(profileId: UUID(), accentGradient: ConversationBackground.pastelBlue.accentGradient)
}
