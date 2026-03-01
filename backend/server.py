"""
Kid Agent Backend — FastAPI server that talks to a local Ollama LLM
with a kid-friendly personality and per-child conversation memory.

Profile data is stored in SQLite (data/kid_agent.db); sensitive columns
are encrypted at rest when KID_AGENT_DB_KEY is set.
"""

import base64
import asyncio
import json
import logging
import os
import re
import typing
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env before other app imports so KID_AGENT_DB_KEY is available
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Configure logging so app messages (e.g. joke API success) are visible in the terminal
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

import config
import db
import llm

logger = logging.getLogger(__name__)

MAX_INTERESTS = config.MAX_INTERESTS
MAX_EXTRACTED_LENGTH = config.MAX_EXTRACTED_LENGTH


def _last_assistant_message(conversation_history: list[dict]) -> str | None:
    """Return the content of the most recent assistant message, or None."""
    for m in reversed(conversation_history):
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip() or None
    return None


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


async def _append_assistant_and_save(
    profile_id: str,
    conversation_history: list[dict],
    conversation_summary: str,
    background_tasks: BackgroundTasks,
) -> bool:
    """Trim history, optionally schedule summary, save. Caller must have already appended the assistant message. Returns True if save succeeded."""
    trimmed = db.trim_history(conversation_history)
    if len(trimmed) >= llm.RECENT_MESSAGES_COUNT and len(trimmed) % llm.RECENT_MESSAGES_COUNT == 0:
        background_tasks.add_task(
            _run_summary_in_background,
            profile_id,
            list(trimmed),
            conversation_summary,
        )
    return await asyncio.to_thread(db.save_history, profile_id, trimmed)


def _attachments_to_response(attachments: list[tuple[bytes, str]]) -> list[dict]:
    """Convert (bytes, media_type) list to list of {caption, image_base64, media_type} for API response."""
    return [
        {"caption": "", "image_base64": base64.b64encode(b).decode(), "media_type": mt}
        for b, mt in attachments
    ]


async def _stream_orchestrator_reply(
    reply: str,
    attachments: list[tuple[bytes, str]],
    profile_id: str,
    conversation_history: list[dict],
    conversation_summary: str,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    """Append reply to history, save, return SSE with done event (reply + optional attachments)."""
    conversation_history.append({"role": "assistant", "content": reply})
    if not await _append_assistant_and_save(profile_id, conversation_history, conversation_summary, background_tasks):
        db.invalidate_history_cache(profile_id)

    def _done_payload() -> dict:
        payload: dict = {"done": True, "reply": reply}
        if attachments:
            payload["attachments"] = _attachments_to_response(attachments)
            if len(attachments) == 1:
                b, mt = attachments[0]
                payload["image_base64"] = base64.b64encode(b).decode()
                payload["image_media_type"] = mt
        return payload

    async def _events() -> typing.AsyncIterator[str]:
        yield f"data: {json.dumps({'token': reply})}\n\n"
        yield f"data: {json.dumps(_done_payload())}\n\n"

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_orchestrator_events(
    profile_id: str,
    conversation_history: list[dict],
    conversation_summary: str,
    background_tasks: BackgroundTasks,
    profile: dict,
    last_assistant: str | None,
    timeout: int,
) -> typing.AsyncIterator[str]:
    """
    Drive the tool-calling orchestrator and yield SSE events: progress (when a picture
    tool is chosen) then token + done with the final reply and attachments.
    """
    llm_reply = ""
    attachments: list[tuple[bytes, str]] = []
    try:
        async for kind, payload in llm.run_chat_with_tools_orchestrator(
            profile,
            conversation_summary,
            conversation_history,
            profile_id,
            last_assistant,
            timeout=timeout,
        ):
            if kind == "progress":
                yield f"data: {json.dumps({'progress': payload})}\n\n"
            elif kind == "token":
                yield f"data: {json.dumps({'token': payload})}\n\n"
            elif kind == "result":
                llm_reply, attachments = payload
                break
    except HTTPException:
        if conversation_history and conversation_history[-1].get("role") == "user":
            conversation_history.pop()
        await asyncio.to_thread(db.save_history, profile_id, conversation_history)
        yield f"data: {json.dumps({'error': 'Request failed.'})}\n\n"
        return

    conversation_history.append({"role": "assistant", "content": llm_reply})
    if not await _append_assistant_and_save(profile_id, conversation_history, conversation_summary, background_tasks):
        db.invalidate_history_cache(profile_id)

    def _done_payload() -> dict:
        payload: dict = {"done": True, "reply": llm_reply}
        if attachments:
            payload["attachments"] = _attachments_to_response(attachments)
            if len(attachments) == 1:
                b, mt = attachments[0]
                payload["image_base64"] = base64.b64encode(b).decode()
                payload["image_media_type"] = mt
        return payload

    # Reply was already streamed token-by-token; sending it again would cause TTS to speak twice.
    yield f"data: {json.dumps(_done_payload())}\n\n"


@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """Non-streaming chat: load profile/history, update profile, call Ollama, save history and optional summary."""
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)

    profile, conversation_summary, conversation_history = await asyncio.gather(
        asyncio.to_thread(db.load_profile_json, profile_id),
        asyncio.to_thread(db.load_summary, profile_id),
        asyncio.to_thread(db.load_history, profile_id),
    )

    profile = update_profile_from_message(profile, user_message)
    if not await asyncio.to_thread(db.save_profile_json, profile_id, profile):
        raise HTTPException(status_code=503, detail="Failed to save profile.")

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = db.trim_history(conversation_history)

    last_assistant = _last_assistant_message(conversation_history)
    llm_reply = ""
    attachments: list[tuple[bytes, str]] = []
    try:
        async for kind, payload in llm.run_chat_with_tools_orchestrator(
            profile,
            conversation_summary,
            conversation_history,
            profile_id,
            last_assistant,
            timeout=config.OLLAMA_CHAT_TIMEOUT,
        ):
            if kind == "result":
                llm_reply, attachments = payload
                break
    except HTTPException:
        if conversation_history and conversation_history[-1]["role"] == "user":
            conversation_history.pop()
        await asyncio.to_thread(db.save_history, profile_id, conversation_history)
        raise

    conversation_history.append({"role": "assistant", "content": llm_reply})
    if not await _append_assistant_and_save(profile_id, conversation_history, conversation_summary, background_tasks):
        raise HTTPException(status_code=503, detail="Failed to save conversation.")

    out: dict = {"reply": llm_reply}
    if attachments:
        out["attachments"] = _attachments_to_response(attachments)
        if len(attachments) == 1:
            b, mt = attachments[0]
            out["image_base64"] = base64.b64encode(b).decode()
            out["image_media_type"] = mt
    return out


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, background_tasks: BackgroundTasks):
    """Stream the assistant reply as Server-Sent Events (SSE)."""
    user_message = request.message.strip()
    if not user_message:
        return {"reply": "Say something and I'll answer!"}

    profile_id = request.profile_id
    await asyncio.to_thread(db.ensure_profile_dir, profile_id)

    profile, conversation_summary, conversation_history = await asyncio.gather(
        asyncio.to_thread(db.load_profile_json, profile_id),
        asyncio.to_thread(db.load_summary, profile_id),
        asyncio.to_thread(db.load_history, profile_id),
    )

    profile = update_profile_from_message(profile, user_message)
    await asyncio.to_thread(db.save_profile_json, profile_id, profile)

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history = db.trim_history(conversation_history)

    last_assistant = _last_assistant_message(conversation_history)
    return StreamingResponse(
        _stream_orchestrator_events(
            profile_id,
            conversation_history,
            conversation_summary,
            background_tasks,
            profile,
            last_assistant,
            config.OLLAMA_CHAT_TIMEOUT,
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
