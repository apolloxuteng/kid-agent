"""
NASA APOD (Astronomy Picture of the Day) integration for Space Mode.
Fetches today's space image and returns image bytes + title/explanation for kid-friendly replies.
Uses NASA_API_KEY (optional; DEMO_KEY has lower rate limits).
"""

import logging
import os
import random
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

APOD_URL = "https://api.nasa.gov/planetary/apod"
APOD_REQUEST_TIMEOUT = 10.0
IMAGE_FETCH_TIMEOUT = 15.0
# APOD archive starts 1995-06-16
APOD_START_DATE = date(1995, 6, 16)

# Phrases that indicate the user is asking for space / astronomy picture of the day
SPACE_REQUEST_PHRASES = (
    "space",
    "astronomy",
    "picture of the day",
    "astronomy picture of the day",
    "show me space",
    "what's in space",
    "astronomy picture",
    "space picture",
    "show me the sky",
    "what's the space picture today",
    "show me the astronomy picture",
    "today's space picture",
    "today's astronomy picture",
    # Another / one more (must include "space" or "astronomy" so we don't steal generic "another picture")
    "another space",
    "another astronomy",
    "another space picture",
    "another astronomy picture",
    "one more space",
    "one more astronomy",
    "show me another space",
    "show me another astronomy",
    "more space",
    "more astronomy",
    "again space",
    "again astronomy",
)

# Generic "one more / another picture" — only treated as Space when last reply was space (see user_asking_for_space).
FOLLOW_UP_PICTURE_PHRASES = (
    "one more picture",
    "another picture",
    "show me one more picture",
    "show me another picture",
    "more picture",
    "again picture",
)

# Substrings that indicate the last assistant reply was a Space (APOD) response.
SPACE_REPLY_INDICATORS = (
    "space picture",
    "today's space",
    "astronomy picture",
    "today's astronomy",
)


def last_message_suggests_space(assistant_message: str | None) -> bool:
    """Return True if the given assistant message looks like a Space (APOD) reply."""
    if not assistant_message or not assistant_message.strip():
        return False
    lower = assistant_message.strip().lower()
    return any(ind in lower for ind in SPACE_REPLY_INDICATORS)


def user_asking_for_another_picture(message: str) -> bool:
    """Return True if the message is a generic request for another/one more picture."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in FOLLOW_UP_PICTURE_PHRASES)


def user_asking_for_space(message: str, last_assistant_message: str | None = None) -> bool:
    """Return True if the message is asking for space/astronomy picture of the day.
    If last_assistant_message is provided and suggests a Space reply, generic follow-ups
    like 'one more picture' or 'another picture' are also treated as Space requests."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    if any(phrase in lower for phrase in SPACE_REQUEST_PHRASES):
        return True
    if last_assistant_message and last_message_suggests_space(last_assistant_message):
        if user_asking_for_another_picture(message):
            return True
    return False


def _parse_media_type(content_type: str | None) -> str:
    """Extract main media type from Content-Type header."""
    if not content_type:
        return "image/jpeg"
    return content_type.split(";")[0].strip().lower() or "image/jpeg"


def _random_apod_date() -> str:
    """Return a random date from APOD start through yesterday (exclude today) as YYYY-MM-DD."""
    today = date.today()
    if today <= APOD_START_DATE:
        return APOD_START_DATE.isoformat()
    days = (today - APOD_START_DATE).days
    # Offset 1 = yesterday, offset days = APOD_START_DATE; exclude today so we get a different picture
    offset = random.randint(1, days) if days >= 1 else 0
    d = today - timedelta(days=offset)
    return d.isoformat()


async def fetch_apod(use_random_date: bool = False) -> tuple[bytes, str, str, str] | None:
    """
    Fetch Astronomy Picture of the Day. Returns (image_bytes, media_type, title, explanation)
    or None on failure or when APOD is a video.

    If use_random_date is True, fetches a random past date (for "one more picture" variety).
    Otherwise fetches today's picture. If the chosen date is a video, retries with another
    random date up to a few times.
    """
    key = (os.environ.get("NASA_API_KEY") or "").strip() or "DEMO_KEY"
    max_tries = 5 if use_random_date else 1
    tried_dates: list[str] = []

    for _ in range(max_tries):
        params: dict[str, str] = {"api_key": key}
        if use_random_date:
            # Avoid reusing the same date we already tried (e.g. video)
            while True:
                d = _random_apod_date()
                if d not in tried_dates:
                    tried_dates.append(d)
                    break
            params["date"] = d

        try:
            async with httpx.AsyncClient(timeout=APOD_REQUEST_TIMEOUT) as client:
                r = await client.get(APOD_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:200]
            logger.warning(
                "NASA APOD request failed: HTTP %s — %s%s",
                e.response.status_code,
                str(e),
                f" Response: {body}" if body else "",
            )
            return None
        except (httpx.TimeoutException, httpx.RequestError, ValueError) as e:
            logger.warning("NASA APOD request failed: %s — %s", type(e).__name__, e)
            return None

        if not isinstance(data, dict):
            return None
        media_type = data.get("media_type")
        if media_type != "image":
            logger.info("APOD is not an image (media_type=%s) for date=%s; skipping", media_type, params.get("date", "today"))
            if not use_random_date:
                return None
            continue

        url = data.get("hdurl") or data.get("url")
        if not url or not isinstance(url, str):
            return None
        title = (data.get("title") or "Today's space picture").strip()
        explanation = (data.get("explanation") or "").strip()

        try:
            async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT) as client:
                img_r = await client.get(url)
                img_r.raise_for_status()
                body = img_r.content
                content_type = img_r.headers.get("content-type")
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning("NASA APOD image fetch failed: %s", e)
            return None

        if not body:
            return None
        parsed_type = _parse_media_type(content_type)
        logger.info("NASA APOD success: date=%s title=%r size=%d", params.get("date", "today"), title, len(body))
        return (body, parsed_type, title, explanation)

    return None
