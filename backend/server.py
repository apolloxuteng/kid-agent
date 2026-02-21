"""
Kid Agent Backend — FastAPI server that talks to a local Ollama LLM
with a kid-friendly personality, conversation memory, and a simple
persistent child profile (name, interests).
"""

import json
import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

# ---------------------------------------------------------------------------
# 1. FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Kid Agent API",
    description="Chat with a local LLM tuned for young children (with conversation memory).",
)

# ---------------------------------------------------------------------------
# 2. Conversation memory (in-memory only — lost when server stops)
# ---------------------------------------------------------------------------
# Each entry: {"role": "user" | "assistant", "content": "text"}
# Prompt uses: system + profile + conversation_summary + last RECENT_MESSAGES_COUNT only.
RECENT_MESSAGES_COUNT = 6
MAX_HISTORY_MESSAGES = 50  # cap full history so summary input stays bounded

conversation_history = []
conversation_summary = ""  # short text, updated every 6 messages via LLM


def trim_history():
    """Keep only the most recent MAX_HISTORY_MESSAGES. Prevents unlimited growth."""
    global conversation_history
    if len(conversation_history) > MAX_HISTORY_MESSAGES:
        conversation_history = conversation_history[-MAX_HISTORY_MESSAGES:]


# ---------------------------------------------------------------------------
# 2b. Child profile (persistent, loaded/saved as JSON file)
# ---------------------------------------------------------------------------
PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "child_profile.json")
MAX_INTERESTS = 10
MAX_EXTRACTED_LENGTH = 80

child_profile = {
    "name": None,
    "interests": [],
}


def load_child_profile():
    """Load profile from child_profile.json if the file exists."""
    global child_profile
    if not os.path.isfile(PROFILE_PATH):
        return
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        child_profile["name"] = data.get("name")
        child_profile["interests"] = data.get("interests", [])
        if not isinstance(child_profile["interests"], list):
            child_profile["interests"] = []
    except (json.JSONDecodeError, OSError):
        pass


def save_child_profile():
    """Write current profile to child_profile.json."""
    try:
        with open(PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(child_profile, f, indent=2)
    except OSError:
        pass


def _sanitize(text: str) -> str | None:
    """Strip whitespace; return None if empty or too long."""
    if not text or len(text) > MAX_EXTRACTED_LENGTH:
        return None
    return text.strip() or None


def update_child_profile(user_message: str):
    """
    Detect simple patterns in the message and update child_profile.
    No LLM call — only string/regex matching. Saves to file when updated.
    """
    global child_profile
    msg = user_message.strip().lower()
    updated = False

    # "my name is X" -> save name
    m = re.search(r"my name is (.+)", msg, re.IGNORECASE)
    if m:
        name = _sanitize(m.group(1).strip())
        if name:
            child_profile["name"] = name
            updated = True

    # "I like X" / "I love X" / "my favorite is X" -> add to interests (no duplicates, max 10)
    for pattern in [
        r"i like (.+?)(?:\.|!|\?|$)",
        r"i love (.+?)(?:\.|!|\?|$)",
        r"my favorite is (.+?)(?:\.|!|\?|$)",
    ]:
        m = re.search(pattern, msg, re.IGNORECASE | re.DOTALL)
        if m:
            raw = m.group(1).strip()
            interest = _sanitize(raw)
            if interest and interest not in child_profile["interests"]:
                child_profile["interests"] = (child_profile["interests"] + [interest])[-MAX_INTERESTS:]
                updated = True

    if updated:
        save_child_profile()


# ---------------------------------------------------------------------------
# 3. Personality system prompt — how the assistant should always behave
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_BASE = """You are a warm, friendly teacher talking to a 6-year-old child.

Rules you always follow:
- Use simple vocabulary. No big or scary words.
- Use short sentences. Maximum 3–4 sentences per reply.
- Be warm and encouraging. Celebrate their curiosity.
- Explain things with simple examples (animals, colors, everyday things).
- You do not need to ask a question every time. Often just reply with a short, warm statement (a reaction, a fact, or encouragement) and let the child lead. Only ask a question occasionally when it fits naturally.
- Never use complex jargon or long explanations.
- Never produce scary, sad, or negative content. Keep everything safe and happy.
- Reply with only your words. Do not include "User:", "Assistant:", or any role labels in your reply.

"""


def get_system_prompt() -> str:
    """
    Returns the system prompt, optionally including the child profile so the
    assistant can reference the child's name and interests naturally.
    """
    out = SYSTEM_PROMPT_BASE
    name = child_profile.get("name")
    interests = child_profile.get("interests") or []
    if name or interests:
        out += "Child Profile:\n"
        if name:
            out += f"- Name: {name}\n"
        if interests:
            out += f"- Interests: {', '.join(interests)}\n"
        out += "\nUse this to personalize when it fits (e.g. use their name sometimes, mention their interests). Do not reference the profile in every message — keep it natural.\n\n"
    return out


# ---------------------------------------------------------------------------
# 4. Ollama configuration — change these if your Ollama runs elsewhere
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"


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
    Called every 6 messages; do not call every turn.
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


# ---------------------------------------------------------------------------
# 5. Request model — what the client sends in the body of POST /chat
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# 6. Strip role labels from model output (fixes completion-style models adding "User:" / "Assistant:")
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 7. Prompt builder — system + profile + summary + recent_messages only
# ---------------------------------------------------------------------------
def build_prompt() -> str:
    """
    Assembles: SYSTEM PROMPT + CHILD PROFILE + CONVERSATION SUMMARY + RECENT MESSAGES (last 6).
    No full history; keeps token usage low for small context windows.
    """
    parts = [get_system_prompt()]

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


# ---------------------------------------------------------------------------
# 8. POST /chat — receive message, update memory, call Ollama, return reply
# ---------------------------------------------------------------------------
@app.post("/chat")
def chat(request: ChatRequest):
    """
    Flow:
    1. Add the user message to conversation_history.
    2. Trim history if it exceeds MAX_HISTORY_MESSAGES.
    3. Build prompt (system + recent history + new message).
    4. Send to Ollama.
    5. Add the assistant reply to conversation_history and trim again.
    6. Return the reply as JSON.
    """
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    # Step 0: Update child profile from message (name, interests) and persist to file
    update_child_profile(user_message)

    # Step 1: Add user message to memory
    conversation_history.append({"role": "user", "content": user_message})
    trim_history()

    # Step 2 & 3: Build prompt (system + profile + summary + last 6 messages)
    full_prompt = build_prompt()

    ollama_payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_URL, json=ollama_payload, timeout=60)

        if response.status_code == 404:
            # Remove the user message we just added so history stays in sync
            if conversation_history and conversation_history[-1]["role"] == "user":
                conversation_history.pop()
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
        raise HTTPException(
            status_code=500,
            detail="Could not reach Ollama. Is it running? Try: ollama serve",
        )
    except requests.exceptions.Timeout:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        raise HTTPException(
            status_code=500,
            detail="Ollama took too long to respond. Try again or check your model.",
        )
    except requests.exceptions.RequestException as e:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        raise HTTPException(
            status_code=500,
            detail=f"Ollama request failed: {str(e)}",
        )

    result = response.json()
    raw_reply = result.get("response", "").strip()
    llm_reply = _strip_role_labels(raw_reply)

    # Step 4: Add assistant reply to memory and trim
    conversation_history.append({"role": "assistant", "content": llm_reply})
    trim_history()

    # Step 5: Every 6 messages, update conversation summary (do not summarize every turn)
    global conversation_summary
    if len(conversation_history) >= 6 and len(conversation_history) % 6 == 0:
        conversation_summary = update_summary(conversation_history, conversation_summary)

    return {"reply": llm_reply}


# ---------------------------------------------------------------------------
# 9. GET /profile — return child profile (name, interests)
# ---------------------------------------------------------------------------
@app.get("/profile")
def get_profile():
    """Returns the stored child profile (name and interests) as JSON."""
    return child_profile


@app.post("/profile/reset")
def reset_profile():
    """Clears the child profile (name and interests) and saves to file."""
    global child_profile
    child_profile = {"name": None, "interests": []}
    save_child_profile()
    return {"status": "profile cleared"}


# ---------------------------------------------------------------------------
# 9. POST /reset — clear conversation memory
# ---------------------------------------------------------------------------
@app.post("/reset")
def reset():
    """Clears all conversation history and summary. Use when starting a new topic or session."""
    global conversation_history, conversation_summary
    conversation_history = []
    conversation_summary = ""
    return {"status": "memory cleared"}


# ---------------------------------------------------------------------------
# 10. Health check + load profile at startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
def startup():
    load_child_profile()


@app.get("/health")
def health():
    """Returns a simple status so clients can check if the server is running."""
    return {"status": "ok"}
