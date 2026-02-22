//
//  KidTheme.swift
//  Kid Chat
//
//  Kid-friendly color theme: calm, not saturated. Shared across chat, profile, and greeting views.
//

import SwiftUI

/// Soft playful palette: pastel blue background, warm orange for user, soft green for AI.
/// Gentle gradients improve depth and feel friendlier than flat colors.
enum KidTheme {
    static let backgroundTop = Color(red: 0.85, green: 0.92, blue: 1.0)      // pastel blue
    static let backgroundBottom = Color(red: 0.92, green: 0.95, blue: 1.0)   // lighter blue
    static let bubbleUserStart = Color(red: 1.0, green: 0.75, blue: 0.45)    // warm orange
    static let bubbleUserEnd = Color(red: 1.0, green: 0.65, blue: 0.35)
    static let bubbleAIStart = Color(red: 0.6, green: 0.88, blue: 0.7)        // soft green
    static let bubbleAIEnd = Color(red: 0.5, green: 0.82, blue: 0.6)
    static let bubbleTextUser = Color.white
    static let bubbleTextAI = Color(red: 0.15, green: 0.2, blue: 0.15)
    static let micIdle = Color(red: 0.35, green: 0.55, blue: 0.95)            // blue
    static let micListening = Color.red
    static let micSpeaking = Color(red: 0.6, green: 0.4, blue: 0.9)          // purple
}
