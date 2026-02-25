"""
shortstories-api (Render) integration: fetch a random short story for kids.
No API key required. Returns title, author, story text, and moral.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

SHORTSTORIES_API_URL = "https://shortstories-api.onrender.com/"
STORY_REQUEST_TIMEOUT = 10.0


def format_story_for_reply(title: str, author: str, story: str, moral: str) -> str:
    """Format a story from the API as a single kid-friendly reply (direct return, no LLM)."""
    parts = [f"{title} by {author}.", story.strip()]
    if moral and moral.strip():
        parts.append(f"The moral of the story: {moral.strip()}")
    return " ".join(parts)


async def fetch_random_story() -> dict | None:
    """
    GET a random short story from shortstories-api.
    Returns dict with keys title, author, story, moral or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=STORY_REQUEST_TIMEOUT) as client:
            r = await client.get(SHORTSTORIES_API_URL)
            r.raise_for_status()
            data = r.json()
            title = data.get("title")
            author = data.get("author")
            story = data.get("story")
            moral = data.get("moral", "")
            if isinstance(title, str) and isinstance(author, str) and isinstance(story, str) and story.strip():
                result = {
                    "title": (title or "").strip(),
                    "author": (author or "").strip(),
                    "story": story.strip(),
                    "moral": (moral or "") if isinstance(moral, str) else "",
                }
                logger.info(
                    "Stories API fetch result: title=%r author=%r story=%r moral=%r",
                    result["title"], result["author"], result["story"][:200], result["moral"]
                )
                return result
            return None
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
        logger.warning("Stories API request failed: %s", e)
        return None
