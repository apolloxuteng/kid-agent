"""
Useless Facts API (jsph.pl) integration: fetch a random fact for the LLM to explain
or use as a story seed. No API key required.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

USELESS_FACTS_API_URL = "https://uselessfacts.jsph.pl/api/v2/facts/random"
FACTS_REQUEST_TIMEOUT = 5.0

# Phrases that indicate the user is asking for a fact or "something interesting"
FACT_REQUEST_PHRASES = (
    "fact",
    "tell me a fact",
    "a fact",
    "give me a fact",
    "something interesting",
    "tell me something interesting",
    "tell me something",
    "fun fact",
    "random fact",
    "learn something",
)

# Phrases that indicate the user is asking for a story (we use a fact as story seed)
STORY_REQUEST_PHRASES = (
    "story",
    "tell me a story",
    "a story",
    "funny story",
    "tell me a funny story",
    "tell me a tale",
    "bedtime story",
    "short story",
)


def user_asking_for_fact(message: str) -> bool:
    """Return True if the message appears to be asking for a fact or something interesting."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in FACT_REQUEST_PHRASES)


def user_asking_for_story(message: str) -> bool:
    """Return True if the message appears to be asking for a story."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in STORY_REQUEST_PHRASES)


async def fetch_random_fact() -> str | None:
    """
    GET a random fact from the Useless Facts API (English).
    Returns the fact text or None on failure (timeout, non-200, invalid JSON).
    """
    try:
        async with httpx.AsyncClient(timeout=FACTS_REQUEST_TIMEOUT) as client:
            r = await client.get(f"{USELESS_FACTS_API_URL}?language=en")
            r.raise_for_status()
            data = r.json()
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                fact_text = text.strip()
                logger.info("Facts API fetch result: %s", fact_text)
                return fact_text
            return None
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
        logger.warning("Facts API request failed: %s", e)
        return None
