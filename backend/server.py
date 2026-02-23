"""
Kid Agent Backend — FastAPI server that talks to a local Ollama LLM
with a kid-friendly personality and per-child conversation memory.

Profile data is stored in SQLite (data/kid_agent.db); sensitive columns
are encrypted at rest when KID_AGENT_DB_KEY is set.
"""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env before other app imports so KID_AGENT_DB_KEY is available
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

import db
import llm

logger = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


MAX_INTERESTS = _env_int("MAX_INTERESTS", 10)
MAX_EXTRACTED_LENGTH = _env_int("MAX_EXTRACTED_LENGTH", 80)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Create DB tables and Ollama HTTP client on startup; close client on shutdown."""
    db.init_db()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
    )
    llm.set_ollama_client(client)
    yield
    llm.set_ollama_client(None)
    await client.aclose()


app = FastAPI(
    title="Kid Agent API",
    description="Chat with a local LLM tuned for young children (per-profile memory).",
    lifespan=_lifespan,
)


# -----------------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """POST /chat body: message and which child profile this conversation belongs to."""
    message: str
    profile_id: str


# -----------------------------------------------------------------------------
# Profile-from-message (name, interests extraction)
# -----------------------------------------------------------------------------

def _sanitize(text: str) -> str | None:
    """Strip whitespace; return None if empty or too long."""
    if not text or len(text) > MAX_EXTRACTED_LENGTH:
        return None
    return text.strip() or None


def update_profile_from_message(profile: dict, user_message: str) -> dict:
    """Detect simple patterns in the message and return an updated profile dict. Caller saves via db.save_profile_json."""
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


# -----------------------------------------------------------------------------
# Background task and endpoints
# -----------------------------------------------------------------------------

async def _run_summary_in_background(profile_id: str, history: list[dict], old_summary: str) -> None:
    """Background task: compute new summary and save to DB."""
    new_summary = await llm.update_summary(history, old_summary)
    if not await asyncio.to_thread(db.save_summary, profile_id, new_summary):
        logger.warning("Background save_summary failed for profile_id=%s", profile_id)


@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """Non-streaming chat: load profile/history, update profile, call Ollama, save history and optional summary."""
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)

    profile = await asyncio.to_thread(db.load_profile_json, profile_id)
    conversation_summary = await asyncio.to_thread(db.load_summary, profile_id)
    conversation_history = await asyncio.to_thread(db.load_history, profile_id)

    profile = update_profile_from_message(profile, user_message)
    if not await asyncio.to_thread(db.save_profile_json, profile_id, profile):
        raise HTTPException(status_code=503, detail="Failed to save profile.")

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = db.trim_history(conversation_history)

    full_prompt = llm.build_prompt(profile, conversation_summary, conversation_history)

    try:
        raw_reply = await llm.call_ollama(
            full_prompt, timeout=llm.OLLAMA_CHAT_TIMEOUT, raise_on_error=True
        )
    except HTTPException:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        await asyncio.to_thread(db.save_history, profile_id, conversation_history)
        raise

    llm_reply = llm.strip_role_labels(raw_reply)

    conversation_history.append({"role": "assistant", "content": llm_reply})
    conversation_history = db.trim_history(conversation_history)

    if len(conversation_history) >= 6 and len(conversation_history) % 6 == 0:
        background_tasks.add_task(
            _run_summary_in_background,
            profile_id,
            list(conversation_history),
            conversation_summary,
        )
    if not await asyncio.to_thread(db.save_history, profile_id, conversation_history):
        raise HTTPException(status_code=503, detail="Failed to save conversation.")

    return {"reply": llm_reply}


async def _stream_chat_sse(
    profile_id: str,
    full_prompt: str,
    conversation_summary: str,
    conversation_history: list[dict],
    background_tasks: BackgroundTasks,
):
    """Stream Ollama tokens as SSE; on completion append reply to history and save."""
    full_reply_parts: list[str] = []
    try:
        if llm.get_ollama_client() is None:
            yield f"data: {json.dumps({'error': 'Ollama client not initialized'})}\n\n"
            return
        async for part in llm.stream_ollama(full_prompt, timeout=llm.OLLAMA_CHAT_TIMEOUT):
            full_reply_parts.append(part)
            yield f"data: {json.dumps({'token': part})}\n\n"

        llm_reply = llm.strip_role_labels("".join(full_reply_parts))
        conversation_history.append({"role": "assistant", "content": llm_reply})
        trimmed = db.trim_history(conversation_history)

        if len(trimmed) >= 6 and len(trimmed) % 6 == 0:
            background_tasks.add_task(
                _run_summary_in_background,
                profile_id,
                list(trimmed),
                conversation_summary,
            )
        if not await asyncio.to_thread(db.save_history, profile_id, trimmed):
            db.invalidate_history_cache(profile_id)
            yield f"data: {json.dumps({'error': 'Failed to save conversation.'})}\n\n"
            return
        yield f"data: {json.dumps({'done': True, 'reply': llm_reply})}\n\n"
    except Exception as e:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        if not await asyncio.to_thread(db.save_history, profile_id, conversation_history):
            db.invalidate_history_cache(profile_id)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """Stream the assistant reply as Server-Sent Events (SSE)."""
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)

    profile = await asyncio.to_thread(db.load_profile_json, profile_id)
    conversation_summary = await asyncio.to_thread(db.load_summary, profile_id)
    conversation_history = await asyncio.to_thread(db.load_history, profile_id)

    profile = update_profile_from_message(profile, user_message)
    await asyncio.to_thread(db.save_profile_json, profile_id, profile)

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = db.trim_history(conversation_history)

    full_prompt = llm.build_prompt(profile, conversation_summary, conversation_history)

    return StreamingResponse(
        _stream_chat_sse(
            profile_id, full_prompt, conversation_summary, conversation_history, background_tasks
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/profile")
async def get_profile(profile_id: str):
    """Returns the stored child profile (name, interests) for the given profile_id."""
    db.validate_profile_id(profile_id)
    return await asyncio.to_thread(db.load_profile_json, profile_id)


@app.post("/profile/reset")
async def reset_profile(profile_id: str):
    """Clears the child profile (name and interests) for this profile_id."""
    db.validate_profile_id(profile_id)
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)
    if not await asyncio.to_thread(db.save_profile_json, profile_id, {"name": None, "interests": []}):
        raise HTTPException(status_code=503, detail="Failed to save profile.")
    return {"status": "profile cleared"}


@app.post("/reset")
async def reset(profile_id: str):
    """Clears conversation history and summary for this profile_id only."""
    db.validate_profile_id(profile_id)
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)
    if not await asyncio.to_thread(db.save_summary, profile_id, ""):
        raise HTTPException(status_code=503, detail="Failed to save.")
    if not await asyncio.to_thread(db.save_history, profile_id, []):
        raise HTTPException(status_code=503, detail="Failed to save.")
    return {"status": "memory cleared"}


@app.get("/health")
async def health():
    """Returns a simple status so clients can check if the server is running."""
    return {"status": "ok"}
