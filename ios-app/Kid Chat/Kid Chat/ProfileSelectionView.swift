//
//  ProfileSelectionView.swift
//  Kid Chat
//
//  Shown when the app starts. Lists all profiles so the user can select who's
//  chatting, then tap Continue to go to the greeting screen. Add Profile to
//  create a new child. If there are no profiles, prompts to add the first one.
//

import SwiftUI

// MARK: - Profile selection (initial screen)

/// Full-screen profile picker shown at launch. Tap a profile to select it; Continue goes to greeting.
struct ProfileSelectionView: View {
    @EnvironmentObject private var profileManager: ProfileManager
    @State private var showAddProfile = false
    @State private var profileToEdit: ChildProfile?

    /// Called when the user taps Continue; move to greeting (or chat).
    var onContinue: () -> Void

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [KidTheme.backgroundTop, KidTheme.backgroundBottom],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            VStack(spacing: 0) {
                // Title
                Text("Who's chatting?")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                    .foregroundStyle(KidTheme.bubbleTextAI)
                    .padding(.top, 32)
                    .padding(.bottom, 24)

                if profileManager.profiles.isEmpty {
                    emptyState
                } else {
                    profileList
                }

                Spacer(minLength: 24)

                // Bottom: Add Profile + Continue
                let atMaxProfiles = profileManager.profiles.count >= ProfileManager.maxProfiles
                VStack(spacing: 14) {
                    Button {
                        if !atMaxProfiles { showAddProfile = true }
                    } label: {
                        Label("Add Profile", systemImage: "plus.circle.fill")
                            .font(.system(size: 18, weight: .semibold, design: .rounded))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                            .background(atMaxProfiles ? Color.gray : KidTheme.micIdle.opacity(0.9))
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .disabled(atMaxProfiles)
                    if atMaxProfiles {
                        Text("Maximum \(ProfileManager.maxProfiles) profiles.")
                            .font(.system(size: 14, weight: .medium, design: .rounded))
                            .foregroundStyle(.secondary)
                    }

                    Button(action: onContinue) {
                        Text("Continue")
                            .font(.system(size: 20, weight: .semibold, design: .rounded))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                            .background(canContinue ? KidTheme.micIdle : Color.gray)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .disabled(!canContinue)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 40)
            }
        }
        .sheet(isPresented: $showAddProfile) {
            AddProfileView(profileManager: profileManager) {
                showAddProfile = false
            }
        }
        .sheet(item: $profileToEdit) { profile in
            EditProfileView(profile: profile, profileManager: profileManager) {
                profileToEdit = nil
            }
        }
    }

    /// Shown when there are no profiles yet.
    private var emptyState: some View {
        VStack(spacing: 20) {
            Text("Add your first profile to get started.")
                .font(.system(size: 18, weight: .medium, design: .rounded))
                .foregroundStyle(KidTheme.bubbleTextAI.opacity(0.9))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 20)
    }

    /// List of profiles; tap to select (sets active).
    private var profileList: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(profileManager.profiles) { profile in
                    profileRow(profile)
                }
            }
            .padding(.horizontal, 24)
        }
        .frame(maxHeight: .infinity)
    }

    private func profileRow(_ profile: ChildProfile) -> some View {
        let isActive = profileManager.activeProfile?.id == profile.id
        return HStack(spacing: 12) {
            Button {
                profileManager.switchProfile(id: profile.id)
            } label: {
                HStack(spacing: 16) {
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
                .padding(.vertical, 12)
                .padding(.horizontal, 16)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(isActive ? KidTheme.micIdle.opacity(0.15) : Color.white.opacity(0.6))
                )
            }
            .buttonStyle(.plain)

            Button {
                profileToEdit = profile
            } label: {
                Image(systemName: "pencil.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(KidTheme.micIdle)
            }
            .buttonStyle(.plain)
        }
        .padding(.bottom, 10)
    }

    /// Continue is enabled when at least one profile exists and one is selected.
    private var canContinue: Bool {
        !profileManager.profiles.isEmpty && profileManager.activeProfile != nil
    }
}

// MARK: - Preview

#Preview {
    ProfileSelectionView(onContinue: {})
        .environmentObject(ProfileManager())
}
