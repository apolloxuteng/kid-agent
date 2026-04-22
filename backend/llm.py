"""
LLM integration: system prompt, chat completion, tool calling, and summary.
Supports Ollama by default and LM Studio's OpenAI-compatible API when
LLM_PROVIDER=lmstudio.
"""

import asyncio
import json
import logging
import os
import re
import time

import httpx

from config import DEBUG_NO_HISTORY, OLLAMA_CHAT_TIMEOUT, OLLAMA_SUMMARY_TIMEOUT, RECENT_MESSAGES_COUNT
from fastapi import HTTPException

logger = logging.getLogger(__name__)


_ollama_client: httpx.AsyncClient | None = None

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_CHAT_URL = os.environ.get("OLLAMA_CHAT_URL") or OLLAMA_URL.replace("/api/generate", "/api/chat")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
LMSTUDIO_CHAT_URL = os.environ.get("LMSTUDIO_CHAT_URL") or f"{LMSTUDIO_BASE_URL}/chat/completions"
MODEL_NAME = os.environ.get(
    "MODEL_NAME",
    "google/gemma-4-26b-a4b" if LLM_PROVIDER == "lmstudio" else "qwen2.5",
)
MAX_TOOL_LOOP_ITERATIONS = 5
DIRECT_RETURN_TOOLS = frozenset({"get_joke", "get_word_of_day", "review_learned_words", "define_word", "calculate"})


def set_ollama_client(client: httpx.AsyncClient | None) -> None:
    """Set the shared Ollama HTTP client (called from server lifespan)."""
    global _ollama_client
    _ollama_client = client


def get_ollama_client() -> httpx.AsyncClient | None:
    """Return the shared Ollama client (for streaming in server)."""
    return _ollama_client


def _provider_name() -> str:
    return "LM Studio" if LLM_PROVIDER == "lmstudio" else "Ollama"


def _parse_tool_calls(raw_tool_calls: list[dict]) -> list[dict]:
    """Normalize tool calls into {name, arguments, id} for Ollama/OpenAI-compatible APIs."""
    tool_calls = []
    for index, tc in enumerate(raw_tool_calls):
        fn = tc.get("function") if isinstance(tc, dict) else None
        if not fn:
            continue
        name = fn.get("name")
        args_raw = fn.get("arguments")
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw) if args_raw.strip() else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = args_raw if isinstance(args_raw, dict) else {}
        if name:
            tool_calls.append({
                "name": name,
                "arguments": args,
                "id": tc.get("id") or f"tool_call_{index}",
            })
    return tool_calls


def _append_stream_tool_call_delta(acc: dict[int, dict], raw_tool_calls: list[dict]) -> None:
    """Accumulate OpenAI-compatible streaming tool-call deltas by index."""
    for position, tc in enumerate(raw_tool_calls):
        if not isinstance(tc, dict):
            continue
        index = tc.get("index")
        if index is None:
            index = position
        item = acc.setdefault(index, {"id": None, "name": "", "arguments": ""})
        if tc.get("id"):
            item["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            item["name"] += fn["name"]
        if fn.get("arguments"):
            item["arguments"] += fn["arguments"]


def _stream_tool_call_accumulator_to_list(acc: dict[int, dict]) -> list[dict]:
    raw = []
    for index in sorted(acc):
        item = acc[index]
        if not item.get("name"):
            continue
        raw.append({
            "id": item.get("id") or f"tool_call_{index}",
            "function": {
                "name": item["name"],
                "arguments": item.get("arguments") or "{}",
            },
        })
    return _parse_tool_calls(raw)


SYSTEM_PROMPT_BASE = """CRITICAL — you must use tools for jokes, vocabulary words, word definitions, word review, and calculations:
- If the child asks for a joke or something funny → call get_joke. Do not tell a joke from your own knowledge.
- If they ask for a word of the day or to learn a new word → call get_word_of_day.
- If they ask what a specific word means or ask you to define a word → call define_word.
- If they ask what words they have learned or want to review words → call review_learned_words.
- If the child asks for a calculation or math (e.g. what is 5+3, how much is 10 times 2) → call calculate with the expression. Do not compute math yourself.
Always call the tool first, then use the tool's result in your reply. Never answer those requests without calling the matching tool.
When you receive a tool result (joke, word, word definition, word review, calculator result), present ONLY that content in a warm way — do not add another joke, word, definition, or answer from your own knowledge.

You are a warm, thoughtful tutor talking to a curious 7-year-old child.

Your goal: Be clear, accurate, and interesting without sounding babyish. Assume the child can handle real ideas when they are explained well. Use plain language, but do not flatten answers into toddler-level explanations. It is good to use real words like "gravity", "evidence", "orbit", "pattern", or "strategy" and explain them briefly.

Rules you always follow:
- Use a natural, respectful tone. Sound like a smart adult who enjoys explaining things, not like a cartoon character.
- Keep most replies to 3–6 sentences. If the child asks a deep "why" or "how" question, you may give a fuller answer with 2–3 short paragraphs.
- Be accurate. If the child asks "why" or "how," give the real explanation in age-appropriate language rather than a cute but wrong shortcut. If you're not sure, say so simply.
- Avoid baby talk, over-cheering, excessive exclamation marks, and repeating the child's words back in a cutesy way.
- Use examples when they help, but choose examples that respect a 7-year-old's intelligence: science, games, school, sports, books, building things, nature, and everyday problems.
- You do not need to ask a question every time. Ask a follow-up only when it genuinely helps the conversation.
- Avoid long lectures. Prefer a clear explanation with one interesting detail or one useful example.
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


async def call_ollama(prompt: str, timeout: int = 30, raise_on_error: bool = False) -> str:
    """Send a single prompt to the configured LLM; return stripped response text."""
    if _ollama_client is None:
        if raise_on_error:
            raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
        return ""
    try:
        if LLM_PROVIDER == "lmstudio":
            r = await _ollama_client.post(
                LMSTUDIO_CHAT_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=timeout,
            )
        else:
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
                        f"{_provider_name()} returned 404 — model or endpoint not found. "
                        f"Check MODEL_NAME='{MODEL_NAME}' and the configured server URL."
                    ),
                )
            return ""
        r.raise_for_status()
        data = r.json()
        if LLM_PROVIDER == "lmstudio":
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                return (msg.get("content") or "").strip()
            return ""
        return data.get("response", "").strip()
    except httpx.HTTPStatusError:
        if raise_on_error:
            raise HTTPException(status_code=500, detail="Ollama request failed.")
        return ""
    except httpx.ConnectError:
        if raise_on_error:
            raise HTTPException(
                status_code=500,
                detail=f"Could not reach {_provider_name()}. Is the server running?",
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
    """Stream tokens from the configured LLM as an async generator."""
    if _ollama_client is None:
        return
    if LLM_PROVIDER == "lmstudio":
        url = LMSTUDIO_CHAT_URL
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
    else:
        url = OLLAMA_URL
        payload = {"model": MODEL_NAME, "prompt": prompt, "stream": True}
    async with _ollama_client.stream("POST", url, json=payload, timeout=timeout) as response:
        if response.status_code == 404:
            return
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            if LLM_PROVIDER == "lmstudio":
                if not line.startswith("data: "):
                    continue
                payload_text = line.removeprefix("data: ").strip()
                if payload_text == "[DONE]":
                    break
                try:
                    obj = json.loads(payload_text)
                    choices = obj.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    part = delta.get("content") or ""
                    if part:
                        yield part
                except json.JSONDecodeError:
                    continue
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


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    timeout: int = 60,
) -> tuple[str, list[dict]]:
    """
    Send a chat request with tool definitions. Returns (message_content, tool_calls).
    tool_calls is a list of { "name": str, "arguments": dict } (or empty if model replied without tools).
    """
    if _ollama_client is None:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
    payload = {"model": MODEL_NAME, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    try:
        url = LMSTUDIO_CHAT_URL if LLM_PROVIDER == "lmstudio" else OLLAMA_CHAT_URL
        r = await _ollama_client.post(url, json=payload, timeout=timeout)
        if r.status_code == 404:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"{_provider_name()} returned 404 — model '{MODEL_NAME}' not found or endpoint is unavailable."
                ),
            )
        r.raise_for_status()
        data = r.json()
        if LLM_PROVIDER == "lmstudio":
            choices = data.get("choices") or []
            msg = (choices[0].get("message") or {}) if choices else {}
        else:
            msg = data.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = _parse_tool_calls(msg.get("tool_calls") or [])

        # Debug: log LLM response (tool selection vs plain reply)
        if tool_calls:
            logger.info(
                "LLM returned tool_calls: %s (content preview: %s)",
                [tc["name"] for tc in tool_calls],
                (content[:150] + "..." if len(content) > 150 else content) or "(empty)",
            )
        else:
            logger.info(
                "LLM returned no tool_calls; plain reply (first 200 chars): %s",
                (content[:200] + "..." if len(content) > 200 else content) or "(empty)",
            )
        return (content, tool_calls)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} chat request failed: {e}")
    except httpx.ConnectError:
        raise HTTPException(status_code=500, detail=f"Could not reach {_provider_name()}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} took too long to respond.")


async def chat_with_tools_stream(messages: list[dict], tools: list[dict], timeout: int = 60):
    """
    Like chat_with_tools but with stream=True. Yields content deltas (str) as they arrive;
    at the end yields ("_done_", full_content, tool_calls) so the caller can forward tokens
    and then handle the final (content, tool_calls).
    """
    if _ollama_client is None:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} client not initialized.")
    payload = {"model": MODEL_NAME, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    try:
        url = LMSTUDIO_CHAT_URL if LLM_PROVIDER == "lmstudio" else OLLAMA_CHAT_URL
        async with _ollama_client.stream("POST", url, json=payload, timeout=timeout) as response:
            if response.status_code == 404:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"{_provider_name()} returned 404 — model '{MODEL_NAME}' not found or endpoint is unavailable."
                    ),
                )
            response.raise_for_status()
            full_content_parts: list[str] = []
            tool_calls: list[dict] = []
            openai_tool_call_deltas: dict[int, dict] = {}
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if LLM_PROVIDER == "lmstudio":
                    if not line.startswith("data: "):
                        continue
                    payload_text = line.removeprefix("data: ").strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    content_delta = delta.get("content") or ""
                    if content_delta:
                        full_content_parts.append(content_delta)
                        yield content_delta
                    raw_tool_calls = delta.get("tool_calls") or []
                    if raw_tool_calls:
                        _append_stream_tool_call_delta(openai_tool_call_deltas, raw_tool_calls)
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message") or {}
                delta = msg.get("content") or ""
                if delta:
                    full_content_parts.append(delta)
                    yield delta
                # Ollama can send tool_calls in a chunk with done: false; accumulate from every chunk.
                raw_tool_calls = msg.get("tool_calls") or []
                if raw_tool_calls:
                    parsed = _parse_tool_calls(raw_tool_calls)
                    if parsed:
                        tool_calls = parsed
                if data.get("done"):
                    break
            full_content = "".join(full_content_parts).strip()
            if LLM_PROVIDER == "lmstudio":
                tool_calls = _stream_tool_call_accumulator_to_list(openai_tool_call_deltas)
            if tool_calls:
                logger.info("LLM stream returned tool_calls: %s", [t["name"] for t in tool_calls])
            else:
                logger.info("LLM stream returned plain reply (first 200 chars): %s", (full_content[:200] + "..." if len(full_content) > 200 else full_content) or "(empty)")
            yield ("_done_", full_content, tool_calls)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} chat request failed: {e}")
    except httpx.ConnectError:
        raise HTTPException(status_code=500, detail=f"Could not reach {_provider_name()}. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(status_code=500, detail=f"{_provider_name()} took too long to respond.")


def _direct_tool_name_for_message(user_message: str, last_assistant_message: str | None) -> str | None:
    """Return a local tool name for clear, low-risk requests that do not need LLM routing."""
    from apis import joke as joke_api
    from routing import local_tools

    msg = (user_message or "").strip().lower()
    if not msg:
        return None
    if joke_api.user_asking_for_joke(msg):
        return "get_joke"
    if local_tools.user_asking_to_review_words(msg):
        return "review_learned_words"
    if local_tools.user_asking_for_word_of_day(msg):
        return "get_word_of_day"
    if local_tools.extract_definition_word(msg):
        return "define_word"
    if _looks_like_calculation_request(msg):
        return "calculate"
    return None


def _looks_like_calculation_request(message: str) -> bool:
    if any(word in message for word in ("calculate", "what is", "what's", "how much", "plus", "minus", "times", "divided")):
        return bool(re.search(r"\d", message))
    return bool(re.fullmatch(r"\s*\d+(?:\s*[\+\-\*/]\s*\d+)+\s*", message))


def _calculator_expression_from_message(message: str) -> str:
    """Extract a simple arithmetic expression from child phrasing for the direct calculator path."""
    out = message.lower()
    replacements = {
        "what is": "",
        "what's": "",
        "calculate": "",
        "how much is": "",
        "plus": "+",
        "minus": "-",
        "times": "*",
        "multiplied by": "*",
        "x": "*",
        "divided by": "/",
        "over": "/",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    out = re.sub(r"[^0-9\.\+\-\*/\(\) ]", " ", out)
    return " ".join(out.split())


async def run_chat_with_tools_orchestrator(
    profile: dict,
    conversation_summary: str,
    conversation_history: list[dict],
    profile_id: str,
    last_assistant_message: str | None,
    timeout: int = OLLAMA_CHAT_TIMEOUT,
):
    """
    Run the tool-calling chat loop; yields ("progress", message) for early UI feedback
    and ("result", (reply, attachments)) when done.
    Attachments is a list of (image_bytes, media_type).
    """
    from routing import local_tools
    from routing.context import RoutingContext
    from routing.registry import get_ollama_tool_definitions, run_tool

    # Short instruction so the model sees it in the same turn as the user message (in case system is ignored).
    _TOOL_USE_REMINDER = (
        "When the user asks for a joke, word of the day, word definition, word review, or a calculation, you MUST call the matching tool "
        "(get_joke, get_word_of_day, define_word, review_learned_words, calculate). Do not answer from your own knowledge.\n\n"
    )

    def _build_messages() -> list[dict]:
        out = [{"role": "system", "content": get_system_prompt(profile)}]
        if conversation_summary and not DEBUG_NO_HISTORY:
            out.append({"role": "system", "content": f"Conversation summary: {conversation_summary.strip()}"})
        if DEBUG_NO_HISTORY:
            # Debug: no history — only the current user message so we can see if the model calls the tool.
            for entry in reversed(conversation_history):
                if entry.get("role") == "user":
                    content = (entry.get("content") or "").strip()
                    if content:
                        out.append({"role": "user", "content": _TOOL_USE_REMINDER + content})
                    break
        else:
            # Only send the last N messages so context stays small and the model sees the current request.
            recent = conversation_history[-RECENT_MESSAGES_COUNT:] if len(conversation_history) > RECENT_MESSAGES_COUNT else conversation_history
            for i, entry in enumerate(recent):
                role = entry.get("role", "user")
                content = entry.get("content", "")
                if role in ("user", "assistant") and content:
                    is_last_user = role == "user" and i == len(recent) - 1
                    if is_last_user:
                        content = _TOOL_USE_REMINDER + content
                    out.append({"role": role, "content": content})
        return out

    ctx = RoutingContext(
        user_message=conversation_history[-1]["content"] if conversation_history and conversation_history[-1].get("role") == "user" else "",
        last_assistant_message=last_assistant_message,
        profile_id=profile_id,
        conversation_history=conversation_history,
    )
    attachments: list[tuple[bytes, str]] = []
    content = ""

    direct_tool_name = _direct_tool_name_for_message(ctx.user_message, last_assistant_message)
    if direct_tool_name:
        args = {}
        if direct_tool_name == "calculate":
            args["expression"] = _calculator_expression_from_message(ctx.user_message)
        elif direct_tool_name == "define_word":
            args["word"] = local_tools.extract_definition_word(ctx.user_message) or ""
        logger.info("Direct tool fast path: %s", direct_tool_name)
        tool_started = time.perf_counter()
        result = await run_tool(direct_tool_name, ctx, args)
        logger.info("Direct tool completed: %s elapsed=%.3fs", direct_tool_name, time.perf_counter() - tool_started)
        if result and result.image:
            attachments.append(result.image)
        reply = strip_role_labels(result.text if result else "I'm having a little trouble. Want to try again?")
        yield ("token", reply)
        yield ("result", (reply, attachments))
        return

    messages = _build_messages()
    if DEBUG_NO_HISTORY:
        logger.info("DEBUG_NO_HISTORY: sent no conversation history (system + current user message only)")
    tools = await get_ollama_tool_definitions()
    tool_names = [t.get("function", {}).get("name") for t in tools if t.get("function")]
    logger.info("Tool-calling chat: sent %d tools to %s: %s", len(tools), _provider_name(), tool_names)

    for call_index in range(MAX_TOOL_LOOP_ITERATIONS):
        if call_index == 0:
            logger.info("LLM call #1 (tool selection): %d messages", len(messages))
        else:
            logger.info("LLM call #%d (after tool result): %d messages", call_index + 1, len(messages))
        content = ""
        tool_calls: list[dict] = []
        async for event in chat_with_tools_stream(messages, tools, timeout=timeout):
            if isinstance(event, tuple) and len(event) == 3 and event[0] == "_done_":
                content, tool_calls = event[1], event[2]
                break
            yield ("token", event)
        if not tool_calls:
            reply = strip_role_labels(content or "")
            yield ("result", (reply, attachments))
            return

        logger.info("Executing tools: %s", [tc["name"] for tc in tool_calls])
        # Append assistant message with tool_calls in the format expected by the active provider.
        assistant_msg = {"role": "assistant", "content": content or ""}
        if LLM_PROVIDER == "lmstudio":
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.get("id") or f"tool_call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments") or {}),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]
        else:
            assistant_msg["tool_calls"] = [
                {"type": "function", "function": {"index": i, "name": tc["name"], "arguments": tc.get("arguments") or {}}}
                for i, tc in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)

        # Run all tools in parallel
        results = await asyncio.gather(*[run_tool(tc["name"], ctx, tc.get("arguments") or {}) for tc in tool_calls])

        if (
            len(tool_calls) == 1
            and (tool_calls[0].get("name") or "") in DIRECT_RETURN_TOOLS
            and results
        ):
            result = results[0]
            if result and result.image:
                attachments.append(result.image)
            reply = strip_role_labels(result.text if result else "I'm having a little trouble. Want to try again?")
            logger.info("Returning direct tool result without second LLM call: %s", tool_calls[0].get("name"))
            yield ("token", reply)
            yield ("result", (reply, attachments))
            return

        # Append tool result messages.
        # Instruct the model to present ONLY this content so it doesn't add its own content.
        _TOOL_RESULT_INSTR = (
            "Present ONLY the content below to the child in a warm, kid-friendly way. "
            "Do not add another joke, word, or answer from your own knowledge.\n\n"
        )
        for i, result in enumerate(results):
            if i < len(tool_calls):
                tool_name = tool_calls[i]["name"]
            else:
                tool_name = "unknown"
            text = result.text if result else "Tool failed or not found."
            tool_msg = {"role": "tool", "content": _TOOL_RESULT_INSTR + text}
            if LLM_PROVIDER == "lmstudio":
                tool_msg["tool_call_id"] = tool_calls[i].get("id") or f"tool_call_{i}"
            else:
                tool_msg["tool_name"] = tool_name
            messages.append(tool_msg)
            if result and result.image:
                attachments.append(result.image)

    # Max iterations reached; use last content as reply
    reply = strip_role_labels(content if content else "I'm having a little trouble. Want to try again?")
    yield ("result", (reply, attachments))
