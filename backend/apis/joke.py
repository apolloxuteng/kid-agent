"""
Official Joke API integration: fetch a random joke and detect when the user asks for one.
Used by the chat flow to inject a joke into the LLM prompt when the child asks.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

OFFICIAL_JOKE_API_URL = "https://official-joke-api.appspot.com/random_joke"
JOKE_REQUEST_TIMEOUT = 5.0

# Phrases that indicate the user is asking for a joke (lowercase, simple checks)
JOKE_REQUEST_PHRASES = (
    "joke",
    "tell me a joke",
    "funny joke",
    "another joke",
    "make me laugh",
    "tell me something funny",
    "something funny",
    "a joke",
    "give me a joke",
    "can you tell me a joke",
    "want to hear a joke",
    "got a joke",
)


def format_joke_for_reply(setup: str, punchline: str) -> str:
    """Format a joke from the API as a single kid-friendly reply (exact setup and punchline, no LLM)."""
    return f"Here's a joke for you! {setup} {punchline}"


def user_asking_for_joke(message: str) -> bool:
    """Return True if the message appears to be asking for a joke. Kept simple to avoid false positives."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in JOKE_REQUEST_PHRASES)


async def fetch_joke() -> tuple[str, str] | None:
    """
    GET a random joke from the Official Joke API.
    Returns (setup, punchline) or None on failure (timeout, non-200, invalid JSON).
    """
    try:
        async with httpx.AsyncClient(timeout=JOKE_REQUEST_TIMEOUT) as client:
            r = await client.get(OFFICIAL_JOKE_API_URL)
            r.raise_for_status()
            data = r.json()
            setup = data.get("setup")
            punchline = data.get("punchline")
            if isinstance(setup, str) and isinstance(punchline, str):
                setup = setup.strip()
                punchline = punchline.strip()
                logger.info("Joke API success: setup=%r punchline=%r", setup, punchline)
                return (setup, punchline)
            return None
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
        logger.warning("Joke API request failed: %s", e)
        return None
