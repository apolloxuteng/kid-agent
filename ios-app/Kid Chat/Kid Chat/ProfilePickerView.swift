//
//  ProfilePickerView.swift
//  Kid Chat
//
//  Sheet that lists all child profiles. Tapping a row switches to that profile.
//  "Add Profile" button presents a form to create a new profile. Shown when the
//  user taps the avatar in the header.
//

import SwiftUI

// MARK: - Profile picker (list + add)

/// Lists all profiles with avatar and name. Tap a row to switch to that profile and dismiss.
/// Includes an "Add Profile" button that presents the add-profile form.
struct ProfilePickerView: View {

    @EnvironmentObject private var profileManager: ProfileManager
    @Environment(\.dismiss) private var dismiss

    /// When true, we show the "Add Profile" form as a sheet on top of this one.
    @State private var showAddProfile = false

    var body: some View {
        NavigationStack {
            ZStack {
                // Same soft background as the rest of the app
                LinearGradient(
                    colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                VStack(spacing: 0) {
                    // List of profiles: avatar + name; tap to switch
                    List {
                        ForEach(profileManager.profiles) { profile in
                            profileRow(profile)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)

                    // Add Profile button at bottom (disabled when at max)
                    let atMaxProfiles = profileManager.profiles.count >= ProfileManager.maxProfiles
                    Button {
                        if !atMaxProfiles { showAddProfile = true }
                    } label: {
                        Label("Add Profile", systemImage: "plus.circle.fill")
                            .font(.system(size: 18, weight: .semibold, design: .rounded))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(atMaxProfiles ? Color.gray : KidTheme.micIdle)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .disabled(atMaxProfiles)
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    if atMaxProfiles {
                        Text("Maximum \(ProfileManager.maxProfiles) profiles.")
                            .font(.system(size: 14, weight: .medium, design: .rounded))
                            .foregroundStyle(.secondary)
                    }
                    Spacer().frame(height: 8)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
            }
            .navigationTitle("Choose profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .font(.system(size: 17, weight: .medium, design: .rounded))
                    .foregroundStyle(KidTheme.micIdle)
                }
            }
            .sheet(isPresented: $showAddProfile) {
                AddProfileView(profileManager: profileManager) {
                    showAddProfile = false
                }
            }
        }
    }

    /// One row: emoji avatar + name. Tap switches active profile and dismisses the sheet.
    private func profileRow(_ profile: ChildProfile) -> some View {
        let isActive = profileManager.activeProfile?.id == profile.id
        return Button {
            profileManager.switchProfile(id: profile.id)
            dismiss()
        } label: {
            HStack(spacing: 16) {
                // Avatar (emoji in circle)
                Text(profile.avatar)
                    .font(.system(size: 44))
                    .frame(width: 56, height: 56)
                    .background(Circle().fill(Color.white.opacity(0.9)))
                    .shadow(color: .black.opacity(0.08), radius: 4, x: 0, y: 2)

                VStack(alignment: .leading, spacing: 2) {
                    Text(profile.name)
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                        .foregroundStyle(KidTheme.bubbleTextAI)
                    Text("Age \(profile.age)")
                        .font(.system(size: 15, weight: .medium, design: .rounded))
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if isActive {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(KidTheme.micIdle)
                        .font(.system(size: 22))
                }
            }
            .padding(.vertical, 8)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Add profile form

/// Simple form to create a new child profile: name, age, interests (comma-separated), avatar (emoji).
/// On save, adds the profile to ProfileManager and calls onDismiss (e.g. close sheet).
struct AddProfileView: View {

    @ObservedObject var profileManager: ProfileManager
    var onDismiss: () -> Void

    @State private var name = ""
    @State private var ageText = ""
    @State private var interestsText = ""
    @State private var avatar = "👤"
    @State private var showMaxProfilesAlert = false

    /// Some friendly default emojis kids might like.
    private let suggestedEmojis = ["🌟", "🦊", "🐶", "🦋", "🌈", "⭐️", "🌸", "🐱", "🦄", "👤"]

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                Form {
                    Section("Name") {
                        TextField("Child's name", text: $name)
                            .font(.system(size: 17, weight: .medium, design: .rounded))
                    }
                    Section("Age") {
                        TextField("Age (number)", text: $ageText)
                            .font(.system(size: 17, weight: .medium, design: .rounded))
                            .keyboardType(.numberPad)
                    }
                    Section("Interests (optional)") {
                        TextField("e.g. soccer, jokes, dinosaurs", text: $interestsText)
                            .font(.system(size: 17, weight: .medium, design: .rounded))
                    }
                    Section("Avatar (emoji)") {
                        TextField("Pick an emoji", text: $avatar)
                            .font(.system(size: 36))
                        // Quick-pick buttons
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 12) {
                                ForEach(suggestedEmojis, id: \.self) { emoji in
                                    Button {
                                        avatar = emoji
                                    } label: {
                                        Text(emoji)
                                            .font(.system(size: 32))
                                            .padding(8)
                                            .background(Circle().fill(avatar == emoji ? KidTheme.micIdle.opacity(0.3) : Color.clear))
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("New profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        onDismiss()
                    }
                    .font(.system(size: 17, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        saveProfile()
                    }
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(canSave ? KidTheme.micIdle : .secondary)
                    .disabled(!canSave)
                }
            }
            .alert("Maximum profiles", isPresented: $showMaxProfilesAlert) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("You can have up to \(ProfileManager.maxProfiles) profiles. Remove one to add another.")
            }
        }
    }

    /// We need at least a non-empty name and a valid age to save.
    private var canSave: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let age = Int(ageText.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return false
        }
        return age >= 0 && age <= 20
    }

    private func saveProfile() {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let age = Int(ageText.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
        let interests = interestsText
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let emoji = avatar.trimmingCharacters(in: .whitespacesAndNewlines)
        let finalAvatar = emoji.isEmpty ? "👤" : String(emoji.prefix(1))

        let profile = ChildProfile(
            name: trimmedName,
            age: age,
            interests: interests,
            avatar: finalAvatar
        )
        if profileManager.addProfile(profile, setActive: true) {
            onDismiss()
        } else {
            showMaxProfilesAlert = true
        }
    }
}

// MARK: - Previews

#Preview("Profile picker") {
    ProfilePickerView()
        .environmentObject(ProfileManager())
}

#Preview("Add profile") {
    AddProfileView(profileManager: ProfileManager()) {}
}
