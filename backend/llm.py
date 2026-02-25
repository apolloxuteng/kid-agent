"""
Ollama LLM integration: system prompt, chat completion, and summary.
Server sets the HTTP client at startup via set_ollama_client().
"""

import json
import os

import httpx

from config import OLLAMA_CHAT_TIMEOUT, OLLAMA_SUMMARY_TIMEOUT, RECENT_MESSAGES_COUNT
from fastapi import HTTPException


_ollama_client: httpx.AsyncClient | None = None

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5")


def set_ollama_client(client: httpx.AsyncClient | None) -> None:
    """Set the shared Ollama HTTP client (called from server lifespan)."""
    global _ollama_client
    _ollama_client = client


def get_ollama_client() -> httpx.AsyncClient | None:
    """Return the shared Ollama client (for streaming in server)."""
    return _ollama_client


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

Silly and mischief requests:
- When the child asks for a silly joke, a "poopoo" or "peepee" joke, or other mischief, stay in the conversation and play along. Do not refuse, lecture, or redirect to a different topic just because the request is silly or mildly potty-themed.
- Mild potty humor and mischief (e.g. light bathroom or silly body jokes) are acceptable and fun for kids. Reply with a short, silly, kid-appropriate joke or reaction. Keep it brief and playful, not crude or explicit.
- Do not say anything truly violating: nothing explicit, harmful, or inappropriate for young children. The line is mischief and fun, not inappropriate.
- If a joke is provided below, deliver it in a warm, kid-friendly way.

"""


def get_system_prompt(profile: dict) -> str:
    """Return the system prompt, optionally including the child profile (name, interests)."""
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


# Stop words for image search keyword fallback (heuristic when LLM extraction fails)
_IMAGE_SEARCH_STOP_WORDS = frozenset(
    {"show", "me", "a", "an", "the", "picture", "of", "i", "want", "to", "see", "image", "photo", "get", "can", "draw", "please", "give", "something", "is", "it", "for", "and", "or"}
)


async def extract_image_search_keywords(user_message: str) -> str:
    """
    Extract 2-5 English keywords for Pixabay image search from the child's message.
    Uses a one-shot LLM call; falls back to heuristic (strip stop words, first 5 words) if LLM fails or returns empty.
    """
    if not user_message or not user_message.strip():
        return ""
    user_message = user_message.strip()[:500]
    prompt = (
        "The child asked for an image. Reply with only 2 to 5 comma-separated English keywords for an image search. Nothing else.\n"
        f"Child's request: {user_message}"
    )
    out = await call_ollama(prompt, timeout=15, raise_on_error=False)
    if out:
        # Take first 100 chars, strip, remove extra commas/spaces
        keywords = " ".join(out.strip().replace(",", " ").split())[:100].strip()
        if keywords:
            return keywords
    # Fallback: heuristic
    words = user_message.lower().replace(",", " ").replace(".", " ").split()
    kept = [w for w in words if w.isalnum() and w not in _IMAGE_SEARCH_STOP_WORDS][:5]
    return " ".join(kept)[:100].strip()


async def call_ollama(prompt: str, timeout: int = 30, raise_on_error: bool = False) -> str:
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
                        f"'ollama pull {MODEL_NAME}' (or set MODEL_NAME to a model you have)."
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
            raise HTTPException(
                status_code=500,
                detail="Could not reach Ollama. Is it running? Try: ollama serve",
            )
        return ""
    except httpx.TimeoutException:
        if raise_on_error:
            raise HTTPException(
                status_code=500,
                detail="Ollama took too long to respond. Try again or check your model.",
            )
        return ""
    except (httpx.RequestError, ValueError) as e:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=f"Ollama request failed: {str(e)}")
        return ""


async def stream_ollama(prompt: str, timeout: int = 60):
    """Stream Ollama tokens as an async generator. Yields token strings."""
    if _ollama_client is None:
        return
    async with _ollama_client.stream(
        "POST",
        OLLAMA_URL,
        json={"model": MODEL_NAME, "prompt": prompt, "stream": True},
        timeout=timeout,
    ) as response:
        if response.status_code == 404:
            return
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                part = obj.get("response", "")
                if part:
                    yield part
                if obj.get("done"):
                    break
            except json.JSONDecodeError:
                continue


async def update_summary(history: list[dict], old_summary: str) -> str:
    """Summarize the conversation for a children's assistant in under 40 words. Returns new summary or old if LLM fails."""
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
    return await call_ollama(prompt, timeout=OLLAMA_SUMMARY_TIMEOUT) or old_summary or ""


def strip_role_labels(text: str) -> str:
    """Remove leading 'Assistant:' / 'User:' so only the reply text is returned."""
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


def build_prompt(
    profile: dict,
    conversation_summary: str,
    conversation_history: list[dict],
    joke: tuple[str, str] | None = None,
    injected_fact: str | None = None,
    story_seed: str | None = None,
) -> str:
    """Assemble SYSTEM PROMPT + CHILD PROFILE + CONVERSATION SUMMARY + [JOKE/FACT/STORY BLOCKS] + RECENT MESSAGES (last 6)."""
    parts = [get_system_prompt(profile)]

    if conversation_summary:
        parts.append("Conversation summary:\n")
        parts.append(conversation_summary.strip())
        parts.append("\n\n")

    if joke is not None:
        setup, punchline = joke
        parts.append("Joke to deliver (use this):\n")
        parts.append(f"Setup: {setup}\n")
        parts.append(f"Punchline: {punchline}\n\n")
        parts.append("Deliver this joke in a warm, kid-friendly way in one or two sentences.\n\n")

    if injected_fact:
        parts.append("Use this fact when answering:\n")
        parts.append(f"{injected_fact}\n\n")
        parts.append("Explain it simply in 2–3 sentences so the child can understand. Keep it warm and engaging.\n\n")

    if story_seed:
        parts.append("Use this idea for a short, funny story:\n")
        parts.append(f"{story_seed}\n\n")
        parts.append(
            "Tell an engaging story based on this idea. For this reply only, you may write a longer story (e.g. 6–10 sentences or a short paragraph) "
            "with a clear beginning, middle, and end. Keep it kid-friendly and fun. The usual 3–4 sentence limit does not apply here.\n\n"
        )

    recent = conversation_history[-RECENT_MESSAGES_COUNT:] if conversation_history else []
    if recent:
        parts.append("Recent messages:\n")
        for entry in recent:
            role = "User" if entry["role"] == "user" else "Assistant"
            parts.append(f"{role}: {entry['content'].strip()}\n")
        parts.append("\n")

    parts.append("Assistant:")
    return "".join(parts)
