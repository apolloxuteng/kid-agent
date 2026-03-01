"""
Pixabay API integration: search for images and return image bytes for kid-friendly
"show me a picture" requests. Uses PIXABAY_API_KEY; safesearch enabled.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

PIXABAY_SEARCH_URL = "https://pixabay.com/api/"
PIXABAY_REQUEST_TIMEOUT = 10.0
IMAGE_FETCH_TIMEOUT = 15.0
MAX_QUERY_LENGTH = 100

# Phrases that indicate the user is asking for an image/picture/photo
IMAGE_REQUEST_PHRASES = (
    "show me a picture",
    "show me a photo",
    "show me an image",
    "i want to see",
    "picture of",
    "photo of",
    "image of",
    "draw me",
    "can i see a picture",
    "get me a photo",
    "want a picture",
    "want to see a picture",
)


def user_asking_for_image(message: str) -> bool:
    """Return True if the message appears to be explicitly asking for an image or picture."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in IMAGE_REQUEST_PHRASES)


def _parse_media_type(content_type: str | None) -> str:
    """Extract main media type from Content-Type header (e.g. 'image/jpeg; charset=...' -> 'image/jpeg')."""
    if not content_type:
        return "image/jpeg"
    return content_type.split(";")[0].strip().lower() or "image/jpeg"


async def fetch_image(search_query: str) -> tuple[bytes, str] | None:
    """
    Search Pixabay for an image matching the query, fetch the first hit's bytes, and return
    (image_bytes, media_type) or None on failure. Uses safesearch=true.
    """
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not key.strip():
        logger.warning("PIXABAY_API_KEY not set; skipping image fetch.")
        return None

    query = search_query.strip()[:MAX_QUERY_LENGTH]
    if not query:
        logger.warning("Empty image search query.")
        return None

    try:
        async with httpx.AsyncClient(timeout=PIXABAY_REQUEST_TIMEOUT) as client:
            r = await client.get(
                PIXABAY_SEARCH_URL,
                params={
                    "key": key,
                    "q": query,
                    "safesearch": "true",
                    "image_type": "photo",
                    "per_page": 5,
                },
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
        logger.warning("Pixabay search failed: %s", e)
        return None

    hits = data.get("hits") if isinstance(data, dict) else None
    if not hits or not isinstance(hits, list):
        logger.info("Pixabay returned no hits for query=%r", query)
        return None

    # Prefer smaller URLs for faster download (app displays at 400x300).
    first = hits[0]
    if not isinstance(first, dict):
        return None
    image_url = first.get("webformatURL") or first.get("previewURL") or first.get("largeImageURL")
    if not image_url or not isinstance(image_url, str):
        return None

    try:
        async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT) as client:
            img_r = await client.get(image_url)
            img_r.raise_for_status()
            body = img_r.content
            content_type = img_r.headers.get("content-type")
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("Pixabay image fetch failed: %s", e)
        return None

    if not body:
        return None

    media_type = _parse_media_type(content_type)
    logger.info("Pixabay image success: query=%r media_type=%s size=%d", query, media_type, len(body))
    return (body, media_type)
