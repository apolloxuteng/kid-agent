"""
Kid Agent Backend — FastAPI server that talks to a local Ollama LLM
with a kid-friendly personality and per-child conversation memory.

Profile data is stored in a single SQLite database (data/kid_agent.db):

  - profiles: profile_id, name, interests (JSON)
  - summaries: profile_id, summary_text
  - history: profile_id, seq, role, content (last N messages per profile)

Sensitive columns are encrypted at rest (application-level). Key via KID_AGENT_DB_KEY.
"""

import asyncio
import copy
import json
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env from the backend directory so KID_AGENT_DB_KEY is available when running uvicorn
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from cryptography.fernet import Fernet, InvalidToken
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

# Optional encryption at rest: set KID_AGENT_DB_KEY to a Fernet key (e.g. from Fernet.generate_key()).
# Losing the key means encrypted data cannot be decrypted. Backups of the DB file must be kept secure.
_DB_KEY_ENV = "KID_AGENT_DB_KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    """Return Fernet instance if KID_AGENT_DB_KEY is set and valid; else None (no encryption)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key_b64 = os.environ.get(_DB_KEY_ENV)
    if not key_b64 or not (key_b64 if isinstance(key_b64, str) else b"").strip():
        return None
    key_bytes = key_b64.strip().encode() if isinstance(key_b64, str) else key_b64
    try:
        _fernet = Fernet(key_bytes)
        return _fernet
    except Exception:
        logger.warning("Invalid %s; running without encryption. Generate a key with: Fernet.generate_key()", _DB_KEY_ENV)
        return None


def _encrypt_cell(plain: str | None) -> str | None:
    """Encrypt a string for storage; return plaintext if encryption is disabled or plain is empty."""
    if plain is None or plain == "":
        return plain
    f = _get_fernet()
    if f is None:
        return plain
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt_cell(cipher: str | None) -> str | None:
    """Decrypt a stored value; if decrypt fails (e.g. legacy plaintext), return as-is."""
    if cipher is None or cipher == "":
        return cipher
    f = _get_fernet()
    if f is None:
        return cipher
    try:
        return f.decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return cipher

# =============================================================================
# 1. App and config
# =============================================================================

logger = logging.getLogger(__name__)

# Ollama: shared async client created at startup, closed at shutdown
_ollama_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Create DB tables and httpx AsyncClient for Ollama on startup; close client on shutdown."""
    global _ollama_client
    init_db()
    _ollama_client = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
    )
    yield
    if _ollama_client is not None:
        await _ollama_client.aclose()
        _ollama_client = None


app = FastAPI(
    title="Kid Agent API",
    description="Chat with a local LLM tuned for young children (per-profile memory).",
    lifespan=_lifespan,
)

# Paths: data folder lives next to server.py (under backend/)
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
PROFILES_ROOT = os.path.join(DATA_DIR, "profiles")
DB_PATH = os.path.join(DATA_DIR, "kid_agent.db")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


# Conversation and profile limits (override via env)
RECENT_MESSAGES_COUNT = _env_int("RECENT_MESSAGES_COUNT", 6)
MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 50)
MAX_INTERESTS = _env_int("MAX_INTERESTS", 10)
MAX_EXTRACTED_LENGTH = _env_int("MAX_EXTRACTED_LENGTH", 80)
MAX_CACHED_PROFILES = _env_int("MAX_CACHED_PROFILES", 20)

# In-memory caches for profile data (invalidated on write / reset)
_profile_cache: dict[str, dict] = {}
_summary_cache: dict[str, str] = {}
_history_cache: dict[str, list] = {}


# =============================================================================
# 2. Profile data: SQLite (data/kid_agent.db)
# =============================================================================

def _validate_profile_id(profile_id: str) -> None:
    """Reject invalid profile_id; raise 400 if invalid."""
    if not profile_id or len(profile_id) > 128:
        raise HTTPException(status_code=400, detail="profile_id is required and must be at most 128 characters")
    if not re.match(r"^[a-zA-Z0-9\-_]+$", profile_id):
        raise HTTPException(status_code=400, detail="profile_id may only contain letters, digits, hyphens, underscores")


def _evict_one_if_needed(cache: dict, new_key: str) -> None:
    """If cache is at capacity and new_key is not present, evict the oldest entry."""
    if len(cache) >= MAX_CACHED_PROFILES and new_key not in cache and cache:
        cache.pop(next(iter(cache)), None)


def init_db() -> None:
    """Create data dir and SQLite tables if they do not exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT,
                interests TEXT
            );
            CREATE TABLE IF NOT EXISTS summaries (
                profile_id TEXT PRIMARY KEY,
                summary_text TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS history (
                profile_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (profile_id, seq)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _ensure_profile_dir(profile_id: str) -> None:
    """Ensure profile and summary rows exist in DB for this profile_id (insert defaults if missing)."""
    _validate_profile_id(profile_id)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO profiles (profile_id, name, interests) VALUES (?, ?, ?)",
            (profile_id, None, "[]"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO summaries (profile_id, summary_text) VALUES (?, ?)",
            (profile_id, ""),
        )
        conn.commit()
    finally:
        conn.close()


def load_profile_json(profile_id: str) -> dict:
    """Load profile for this profile_id; return { name, interests } with defaults. Uses in-memory cache."""
    if profile_id in _profile_cache:
        return copy.deepcopy(_profile_cache[profile_id])
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT name, interests FROM profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            out = {"name": None, "interests": []}
        else:
            name_raw, interests_raw = row[0], row[1]
            name = _decrypt_cell(name_raw)
            interests = []
            if interests_raw:
                try:
                    interests_json = _decrypt_cell(interests_raw) or "[]"
                    interests = json.loads(interests_json)
                    if not isinstance(interests, list):
                        interests = []
                except (json.JSONDecodeError, TypeError):
                    pass
            out = {"name": name, "interests": interests}
        _evict_one_if_needed(_profile_cache, profile_id)
        _profile_cache[profile_id] = out
        return copy.deepcopy(out)
    finally:
        conn.close()


def save_profile_json(profile_id: str, data: dict) -> bool:
    """Write profile for this profile_id and update cache. Returns True on success."""
    _ensure_profile_dir(profile_id)
    name_val = data.get("name")
    interests_json = json.dumps(data.get("interests") or [])
    name_stored = _encrypt_cell(name_val if name_val is None else str(name_val))
    interests_stored = _encrypt_cell(interests_json)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO profiles (profile_id, name, interests) VALUES (?, ?, ?)",
            (profile_id, name_stored, interests_stored),
        )
        conn.commit()
        _profile_cache[profile_id] = copy.deepcopy(data)
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save profile for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


def load_summary(profile_id: str) -> str:
    """Load summary for this profile_id; return empty string if missing. Uses in-memory cache."""
    if profile_id in _summary_cache:
        return _summary_cache[profile_id]
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT summary_text FROM summaries WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        raw = (row[0] or "").strip() if row else ""
        text = (_decrypt_cell(raw) or "").strip()
        _evict_one_if_needed(_summary_cache, profile_id)
        _summary_cache[profile_id] = text
        return text
    finally:
        conn.close()


def save_summary(profile_id: str, text: str) -> bool:
    """Write summary for this profile_id and update cache. Returns True on success."""
    _ensure_profile_dir(profile_id)
    stored = _encrypt_cell(text or "") or ""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO summaries (profile_id, summary_text) VALUES (?, ?)",
            (profile_id, stored),
        )
        conn.commit()
        _summary_cache[profile_id] = text
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save summary for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


def load_history(profile_id: str) -> list[dict]:
    """Load last MAX_HISTORY_MESSAGES for this profile_id; list of { role, content }. Uses in-memory cache."""
    if profile_id in _history_cache:
        return copy.deepcopy(_history_cache[profile_id])
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT role, content FROM history
            WHERE profile_id = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (profile_id, MAX_HISTORY_MESSAGES),
        ).fetchall()
        out = []
        for role, content_raw in reversed(rows):
            content = _decrypt_cell(content_raw) if content_raw else ""
            if role in ("user", "assistant") and isinstance(content, str):
                out.append({"role": role, "content": content})
        _evict_one_if_needed(_history_cache, profile_id)
        _history_cache[profile_id] = out
        return copy.deepcopy(out)
    finally:
        conn.close()


def save_history(profile_id: str, history: list[dict]) -> bool:
    """Replace history for this profile_id with the given list (last N only) and update cache."""
    _ensure_profile_dir(profile_id)
    trimmed = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM history WHERE profile_id = ?", (profile_id,))
        for seq, entry in enumerate(trimmed, start=1):
            if isinstance(entry, dict) and entry.get("role") in ("user", "assistant") and isinstance(entry.get("content"), str):
                content_stored = _encrypt_cell(entry["content"]) or ""
                conn.execute(
                    "INSERT INTO history (profile_id, seq, role, content) VALUES (?, ?, ?, ?)",
                    (profile_id, seq, entry["role"], content_stored),
                )
        conn.commit()
        _history_cache[profile_id] = copy.deepcopy(trimmed)
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save history for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


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

SYSTEM_PROMPT_BASE = """You are a warm, friendly teacher talking to an 8-year-old child.

Your goal: Be simple and easy to understand, but accurate. Explain real ideas in plain language — never dumb down facts so much that they become wrong or vague. It's okay to use a real word (e.g. "gravity", "planet") and then explain it in one short phrase.

Rules you always follow:
- Use clear, plain language and short sentences. Maximum 3–4 sentences per reply.
- Be accurate. If the child asks "why" or "how," give a correct explanation in simple terms rather than a cutesy wrong one. If you're not sure, say so simply.
- Be warm and encouraging without being babyish. Avoid excessive exclamations, baby talk, or repeating their words back in a cutesy way every time.
- Explain with simple examples when they help (animals, everyday things), but keep the underlying idea correct.
- You do not need to ask a question every time. Often just reply with a short, warm statement (a reaction, a fact, or encouragement) and let the child lead. Only ask a question occasionally when it fits naturally.
- Avoid long explanations or jargon. Prefer one clear, accurate idea over a long or fuzzy one.
- Reply in English only. Do not mix in Chinese or other languages unless the child explicitly asks you to (e.g. "say it in Chinese" or "what's the Chinese word for …").
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


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5")
OLLAMA_CHAT_TIMEOUT = _env_int("OLLAMA_CHAT_TIMEOUT", 60)
OLLAMA_SUMMARY_TIMEOUT = _env_int("OLLAMA_SUMMARY_TIMEOUT", 30)


async def _call_ollama(prompt: str, timeout: int = 30, raise_on_error: bool = False) -> str:
    """Send a single prompt to Ollama; return stripped response text. If raise_on_error, raise HTTPException on failure."""
    if _ollama_client is None:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Ollama client not initialized.")
        return ""
    try:
        r = await _ollama_client.post(
            OLLAMA_URL,
            json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        if r.status_code == 404:
            if raise_on_error:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Ollama returned 404 — model '{MODEL_NAME}' not found. "
                        f"Run 'ollama list' to see installed models, then "
                        f"'ollama pull {MODEL_NAME}' (or set MODEL_NAME in server.py to a model you have)."
                    ),
                )
            return ""
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except httpx.HTTPStatusError:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Ollama request failed.")
        return ""
    except httpx.ConnectError:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Could not reach Ollama. Is it running? Try: ollama serve")
        return ""
    except httpx.TimeoutException:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Ollama took too long to respond. Try again or check your model.")
        return ""
    except (httpx.RequestError, ValueError) as e:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=f"Ollama request failed: {str(e)}")
        return ""


async def update_summary(history: list[dict], old_summary: str) -> str:
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
    return await _call_ollama(prompt, timeout=OLLAMA_SUMMARY_TIMEOUT) or old_summary or ""


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

async def _run_summary_in_background(profile_id: str, history: list[dict], old_summary: str) -> None:
    """Background task: compute new summary and save to disk. Does not block the response."""
    new_summary = await update_summary(history, old_summary)
    if not await asyncio.to_thread(save_summary, profile_id, new_summary):
        logger.warning("Background save_summary failed for profile_id=%s", profile_id)


@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Flow:
    1. Validate profile_id and ensure data/profiles/{profile_id}/ exists.
    2. Load this profile's profile.json, summary.txt, history.json.
    3. Update profile from message (name, interests); save profile.json.
    4. Append user message to history, trim, build prompt, call Ollama.
    5. Append assistant reply to history; every 6 messages schedule summary update in background.
    6. Save history.json and return reply immediately (summary runs async).
    """
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(_ensure_profile_dir, profile_id)

    # Load profile-specific data (no cross-profile state)
    profile = await asyncio.to_thread(load_profile_json, profile_id)
    conversation_summary = await asyncio.to_thread(load_summary, profile_id)
    conversation_history = await asyncio.to_thread(load_history, profile_id)

    # Update profile from message and persist
    profile = update_profile_from_message(profile, user_message)
    if not await asyncio.to_thread(save_profile_json, profile_id, profile):
        raise HTTPException(status_code=503, detail="Failed to save profile.")

    # Add user message and trim
    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = trim_history(conversation_history)

    full_prompt = build_prompt(profile, conversation_summary, conversation_history)

    try:
        raw_reply = await _call_ollama(full_prompt, timeout=OLLAMA_CHAT_TIMEOUT, raise_on_error=True)
    except HTTPException:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        await asyncio.to_thread(save_history, profile_id, conversation_history)
        raise

    llm_reply = _strip_role_labels(raw_reply)

    conversation_history.append({"role": "assistant", "content": llm_reply})
    conversation_history = trim_history(conversation_history)

    if len(conversation_history) >= 6 and len(conversation_history) % 6 == 0:
        # Run summary in background so we return the reply immediately
        background_tasks.add_task(
            _run_summary_in_background,
            profile_id,
            list(conversation_history),  # copy so background task has exact state
            conversation_summary,
        )
    if not await asyncio.to_thread(save_history, profile_id, conversation_history):
        raise HTTPException(status_code=503, detail="Failed to save conversation.")

    return {"reply": llm_reply}


async def _stream_chat_sse(
    profile_id: str,
    full_prompt: str,
    conversation_summary: str,
    conversation_history: list[dict],
    background_tasks: BackgroundTasks,
):
    """Async generator: stream Ollama tokens as SSE; on completion append reply to history and save.
    Cache consistency: _history_cache is updated only inside save_history() on success; on save failure we pop(profile_id) so the next load reads from disk."""
    full_reply_parts: list[str] = []
    try:
        if _ollama_client is None:
            yield f"data: {json.dumps({'error': 'Ollama client not initialized'})}\n\n"
            return
        async with _ollama_client.stream(
            "POST",
            OLLAMA_URL,
            json={"model": MODEL_NAME, "prompt": full_prompt, "stream": True},
            timeout=OLLAMA_CHAT_TIMEOUT,
        ) as response:
            if response.status_code == 404:
                yield f"data: {json.dumps({'error': f'Model {MODEL_NAME} not found'})}\n\n"
                return
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    part = obj.get("response", "")
                    if part:
                        full_reply_parts.append(part)
                        yield f"data: {json.dumps({'token': part})}\n\n"
                    if obj.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        llm_reply = _strip_role_labels("".join(full_reply_parts))
        conversation_history.append({"role": "assistant", "content": llm_reply})
        trimmed = trim_history(conversation_history)
        if len(trimmed) >= 6 and len(trimmed) % 6 == 0:
            background_tasks.add_task(
                _run_summary_in_background,
                profile_id,
                list(trimmed),
                conversation_summary,
            )
        if not await asyncio.to_thread(save_history, profile_id, trimmed):
            _history_cache.pop(profile_id, None)
            yield f"data: {json.dumps({'error': 'Failed to save conversation.'})}\n\n"
            return
        yield f"data: {json.dumps({'done': True, 'reply': llm_reply})}\n\n"
    except Exception as e:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        if not await asyncio.to_thread(save_history, profile_id, conversation_history):
            _history_cache.pop(profile_id, None)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Same as POST /chat but streams the assistant reply as Server-Sent Events (SSE).
    Each event is a JSON object: { "token": "..." } for each token, then { "done": true, "reply": "..." } at end.
    On error, sends { "error": "..." }. Client should accumulate "token" values and use "reply" when done.
    """
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(_ensure_profile_dir, profile_id)

    profile = await asyncio.to_thread(load_profile_json, profile_id)
    conversation_summary = await asyncio.to_thread(load_summary, profile_id)
    conversation_history = await asyncio.to_thread(load_history, profile_id)

    profile = update_profile_from_message(profile, user_message)
    await asyncio.to_thread(save_profile_json, profile_id, profile)

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = trim_history(conversation_history)

    full_prompt = build_prompt(profile, conversation_summary, conversation_history)

    return StreamingResponse(
        _stream_chat_sse(profile_id, full_prompt, conversation_summary, conversation_history, background_tasks),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/profile")
async def get_profile(profile_id: str):
    """Returns the stored child profile (name, interests) for the given profile_id."""
    _validate_profile_id(profile_id)
    return await asyncio.to_thread(load_profile_json, profile_id)


@app.post("/profile/reset")
async def reset_profile(profile_id: str):
    """Clears the child profile (name and interests) for this profile_id and saves to file."""
    _validate_profile_id(profile_id)
    await asyncio.to_thread(_ensure_profile_dir, profile_id)
    if not await asyncio.to_thread(save_profile_json, profile_id, {"name": None, "interests": []}):
        raise HTTPException(status_code=503, detail="Failed to save profile.")
    return {"status": "profile cleared"}


@app.post("/reset")
async def reset(profile_id: str):
    """Clears conversation history and summary for this profile_id only."""
    _validate_profile_id(profile_id)
    await asyncio.to_thread(_ensure_profile_dir, profile_id)
    if not await asyncio.to_thread(save_summary, profile_id, ""):
        raise HTTPException(status_code=503, detail="Failed to save.")
    if not await asyncio.to_thread(save_history, profile_id, []):
        raise HTTPException(status_code=503, detail="Failed to save.")
    return {"status": "memory cleared"}


@app.get("/health")
async def health():
    """Returns a simple status so clients can check if the server is running."""
    return {"status": "ok"}
