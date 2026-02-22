"""
Kid Agent Backend — FastAPI server that talks to a local Ollama LLM
with a kid-friendly personality and per-child conversation memory.

All code lives in this file. Profile data is stored under the backend folder:

  backend/
  └── data/
       └── profiles/
            └── {profile_id}/          e.g. spencer, or a UUID from the app
                 ├── profile.json      name, interests (updated from messages)
                 ├── summary.txt      short conversation summary
                 └── history.json     recent messages for context

Folders are created automatically when a profile is first used. No database.
"""

import json
import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

# =============================================================================
# 1. App and config
# =============================================================================

app = FastAPI(
    title="Kid Agent API",
    description="Chat with a local LLM tuned for young children (per-profile memory).",
)

# Paths: data folder lives next to server.py (under backend/)
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
PROFILES_ROOT = os.path.join(DATA_DIR, "profiles")

# Conversation and profile limits
RECENT_MESSAGES_COUNT = 6
MAX_HISTORY_MESSAGES = 50
MAX_INTERESTS = 10
MAX_EXTRACTED_LENGTH = 80


@app.on_event("startup")
def _ensure_data_dirs():
    """Create data/ and data/profiles/ under backend so the folder structure exists."""
    os.makedirs(PROFILES_ROOT, exist_ok=True)


# =============================================================================
# 2. Profile data: paths and file I/O (data/profiles/{profile_id}/)
# =============================================================================

def _validate_profile_id(profile_id: str) -> None:
    """Reject invalid profile_id to avoid path traversal; raise 400 if invalid."""
    if not profile_id or len(profile_id) > 128:
        raise HTTPException(status_code=400, detail="profile_id is required and must be at most 128 characters")
    if not re.match(r"^[a-zA-Z0-9\-_]+$", profile_id):
        raise HTTPException(status_code=400, detail="profile_id may only contain letters, digits, hyphens, underscores")


def _profile_dir(profile_id: str) -> str:
    """Return the absolute path to this profile's folder (e.g. .../data/profiles/spencer/)."""
    _validate_profile_id(profile_id)
    return os.path.join(PROFILES_ROOT, profile_id)


def _ensure_profile_dir(profile_id: str) -> str:
    """Create data/profiles/{profile_id}/ if it does not exist. Return the folder path."""
    path = _profile_dir(profile_id)
    os.makedirs(path, exist_ok=True)
    return path


def _path(profile_id: str, filename: str) -> str:
    """Path to a file inside this profile's folder (e.g. profile.json, summary.txt, history.json)."""
    return os.path.join(_profile_dir(profile_id), filename)


def load_profile_json(profile_id: str) -> dict:
    """Load profile.json for this profile; return { name, interests } with defaults."""
    path = _path(profile_id, "profile.json")
    if not os.path.isfile(path):
        return {"name": None, "interests": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name")
        interests = data.get("interests", [])
        if not isinstance(interests, list):
            interests = []
        return {"name": name, "interests": interests}
    except (json.JSONDecodeError, OSError):
        return {"name": None, "interests": []}


def save_profile_json(profile_id: str, data: dict) -> None:
    """Write profile.json for this profile."""
    _ensure_profile_dir(profile_id)
    path = _path(profile_id, "profile.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def load_summary(profile_id: str) -> str:
    """Load summary.txt for this profile; return empty string if missing."""
    path = _path(profile_id, "summary.txt")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_summary(profile_id: str, text: str) -> None:
    """Write summary.txt for this profile."""
    _ensure_profile_dir(profile_id)
    path = _path(profile_id, "summary.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def load_history(profile_id: str) -> list[dict]:
    """Load history.json for this profile; list of { role, content }. Return [] if missing or invalid."""
    path = _path(profile_id, "history.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and e.get("role") in ("user", "assistant") and isinstance(e.get("content"), str)]
    except (json.JSONDecodeError, OSError):
        return []


def save_history(profile_id: str, history: list[dict]) -> None:
    """Write history.json for this profile."""
    _ensure_profile_dir(profile_id)
    path = _path(profile_id, "history.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def trim_history(history: list[dict]) -> list[dict]:
    """Return the last MAX_HISTORY_MESSAGES entries. Does not mutate in place."""
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    return history[-MAX_HISTORY_MESSAGES:]


# =============================================================================
# 3. Update profile from message (name, interests) — caller saves to profile.json
# =============================================================================

def _sanitize(text: str) -> str | None:
    """Strip whitespace; return None if empty or too long."""
    if not text or len(text) > MAX_EXTRACTED_LENGTH:
        return None
    return text.strip() or None


def update_profile_from_message(profile: dict, user_message: str) -> dict:
    """
    Detect simple patterns in the message and return an updated profile dict.
    No LLM call — only string/regex. Caller should save via save_profile_json.
    """
    out = {"name": profile.get("name"), "interests": list(profile.get("interests") or [])}
    msg = user_message.strip().lower()

    m = re.search(r"my name is (.+)", msg, re.IGNORECASE)
    if m:
        name = _sanitize(m.group(1).strip())
        if name:
            out["name"] = name

    for pattern in [
        r"i like (.+?)(?:\.|!|\?|$)",
        r"i love (.+?)(?:\.|!|\?|$)",
        r"my favorite is (.+?)(?:\.|!|\?|$)",
    ]:
        m = re.search(pattern, msg, re.IGNORECASE | re.DOTALL)
        if m:
            raw = m.group(1).strip()
            interest = _sanitize(raw)
            if interest and interest not in out["interests"]:
                out["interests"] = (out["interests"] + [interest])[-MAX_INTERESTS:]

    return out


# =============================================================================
# 4. LLM: system prompt and Ollama
# =============================================================================

SYSTEM_PROMPT_BASE = """You are a warm, friendly teacher talking to a 8-year-old child.

Rules you always follow:
- Use simple vocabulary.
- Use short sentences. Maximum 3–4 sentences per reply.
- Be warm and encouraging. Celebrate their curiosity.
- Explain things with simple examples (animals, colors, everyday things).
- You do not need to ask a question every time. Often just reply with a short, warm statement (a reaction, a fact, or encouragement) and let the child lead. Only ask a question occasionally when it fits naturally.
- Never use complex jargon or long explanations.
- Reply with only your words. Do not include "User:", "Assistant:", or any role labels in your reply.

"""


def get_system_prompt(profile: dict) -> str:
    """
    Returns the system prompt, optionally including the child profile so the
    assistant can reference the child's name and interests naturally.
    """
    out = SYSTEM_PROMPT_BASE
    name = profile.get("name")
    interests = profile.get("interests") or []
    if name or interests:
        out += "Child Profile:\n"
        if name:
            out += f"- Name: {name}\n"
        if interests:
            out += f"- Interests: {', '.join(interests)}\n"
        out += "\nUse this to personalize when it fits (e.g. use their name sometimes, mention their interests). Do not reference the profile in every message — keep it natural.\n\n"
    return out


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5"


def _call_ollama(prompt: str, timeout: int = 30) -> str:
    """Send a single prompt to Ollama; return stripped response text."""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except (requests.exceptions.RequestException, ValueError):
        return ""


def update_summary(history: list[dict], old_summary: str) -> str:
    """
    Summarize the conversation for a children's assistant in under 40 words.
    Called every 6 messages; do not call every turn. Returns new summary (or old if LLM fails).
    """
    if not history:
        return old_summary or ""
    lines = []
    for entry in history:
        role = "User" if entry["role"] == "user" else "Assistant"
        lines.append(f"{role}: {entry['content'].strip()}")
    conv_block = "\n".join(lines)
    prev = f"Previous summary: {old_summary}\n\n" if old_summary else ""
    prompt = f"""Summarize the conversation for a children's assistant in under 40 words.

{prev}Conversation:
{conv_block}

Summary:"""
    return _call_ollama(prompt) or old_summary or ""


# =============================================================================
# 5. Request models
# =============================================================================

class ChatRequest(BaseModel):
    """POST /chat body: message and which child profile this conversation belongs to."""
    message: str
    profile_id: str  # e.g. UUID string from the app; used as folder name under data/profiles/


# =============================================================================
# 6. Helpers: strip role labels from LLM output, build prompt
# =============================================================================

def _strip_role_labels(text: str) -> str:
    """Remove leading 'Assistant:' / 'User:' and similar so only the reply text is returned.
    Helps especially with smaller completion-style models; larger chat models often follow
    the 'no role labels' instruction better, but stripping is a safe fallback for any size."""
    if not text:
        return text
    out = text.strip()
    while True:
        lower = out.lower().lstrip()
        if lower.startswith("assistant:"):
            out = out[out.lower().find("assistant:") + len("assistant:") :].strip()
        elif lower.startswith("user:"):
            out = out[out.lower().find("user:") + len("user:") :].strip()
        else:
            break
    return out.strip()


def build_prompt(profile: dict, conversation_summary: str, conversation_history: list[dict]) -> str:
    """
    Assembles: SYSTEM PROMPT + CHILD PROFILE + CONVERSATION SUMMARY + RECENT MESSAGES (last 6).
    No full history; keeps token usage low for small context windows.
    """
    parts = [get_system_prompt(profile)]

    if conversation_summary:
        parts.append("Conversation summary:\n")
        parts.append(conversation_summary.strip())
        parts.append("\n\n")

    recent = conversation_history[-RECENT_MESSAGES_COUNT:] if conversation_history else []
    if recent:
        parts.append("Recent messages:\n")
        for entry in recent:
            role = "User" if entry["role"] == "user" else "Assistant"
            parts.append(f"{role}: {entry['content'].strip()}\n")
        parts.append("\n")

    parts.append("Assistant:")
    return "".join(parts)


# =============================================================================
# 7. Endpoints: chat, profile, reset, health
# =============================================================================

@app.post("/chat")
def chat(request: ChatRequest):
    """
    Flow:
    1. Validate profile_id and ensure data/profiles/{profile_id}/ exists.
    2. Load this profile's profile.json, summary.txt, history.json.
    3. Update profile from message (name, interests); save profile.json.
    4. Append user message to history, trim, build prompt, call Ollama.
    5. Append assistant reply to history; every 6 messages update summary.
    6. Save summary.txt and history.json for this profile only.
    """
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    _ensure_profile_dir(profile_id)  # create folder if missing

    # Load profile-specific data (no cross-profile state)
    profile = load_profile_json(profile_id)
    conversation_summary = load_summary(profile_id)
    conversation_history = load_history(profile_id)

    # Update profile from message and persist
    profile = update_profile_from_message(profile, user_message)
    save_profile_json(profile_id, profile)

    # Add user message and trim
    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = trim_history(conversation_history)

    full_prompt = build_prompt(profile, conversation_summary, conversation_history)
    ollama_payload = {"model": MODEL_NAME, "prompt": full_prompt, "stream": False}

    try:
        response = requests.post(OLLAMA_URL, json=ollama_payload, timeout=60)

        if response.status_code == 404:
            if conversation_history and conversation_history[-1]["role"] == "user":
                conversation_history.pop()
            save_history(profile_id, conversation_history)
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Ollama returned 404 — model '{MODEL_NAME}' not found. "
                    f"Run 'ollama list' to see installed models, then "
                    f"'ollama pull {MODEL_NAME}' (or set MODEL_NAME in server.py to a model you have)."
                ),
            )
        response.raise_for_status()
    except HTTPException:
        raise
    except requests.exceptions.ConnectionError:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        save_history(profile_id, conversation_history)
        raise HTTPException(status_code=500, detail="Could not reach Ollama. Is it running? Try: ollama serve")
    except requests.exceptions.Timeout:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        save_history(profile_id, conversation_history)
        raise HTTPException(status_code=500, detail="Ollama took too long to respond. Try again or check your model.")
    except requests.exceptions.RequestException as e:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        save_history(profile_id, conversation_history)
        raise HTTPException(status_code=500, detail=f"Ollama request failed: {str(e)}")

    result = response.json()
    raw_reply = result.get("response", "").strip()
    llm_reply = _strip_role_labels(raw_reply)

    conversation_history.append({"role": "assistant", "content": llm_reply})
    conversation_history = trim_history(conversation_history)

    if len(conversation_history) >= 6 and len(conversation_history) % 6 == 0:
        conversation_summary = update_summary(conversation_history, conversation_summary)
        save_summary(profile_id, conversation_summary)
    save_history(profile_id, conversation_history)

    return {"reply": llm_reply}


@app.get("/profile")
def get_profile(profile_id: str):
    """Returns the stored child profile (name, interests) for the given profile_id."""
    _validate_profile_id(profile_id)
    return load_profile_json(profile_id)


@app.post("/profile/reset")
def reset_profile(profile_id: str):
    """Clears the child profile (name and interests) for this profile_id and saves to file."""
    _validate_profile_id(profile_id)
    _ensure_profile_dir(profile_id)
    save_profile_json(profile_id, {"name": None, "interests": []})
    return {"status": "profile cleared"}


@app.post("/reset")
def reset(profile_id: str):
    """Clears conversation history and summary for this profile_id only."""
    _validate_profile_id(profile_id)
    _ensure_profile_dir(profile_id)
    save_summary(profile_id, "")
    save_history(profile_id, [])
    return {"status": "memory cleared"}


@app.get("/health")
def health():
    """Returns a simple status so clients can check if the server is running."""
    return {"status": "ok"}
