"""
Open Trivia DB integration for Quiz Mode. Fetches one easy multiple-choice question
for kid-friendly trivia. No API key; rate limit 1 request per 5 seconds per IP.
"""

import html
import logging
import random

import httpx

logger = logging.getLogger(__name__)

OPENTDB_URL = "https://opentdb.com/api.php"
TRIVIA_REQUEST_TIMEOUT = 8.0

# Kid-friendly category IDs: General Knowledge, Science & Nature, Sports, Geography, Animals
KID_FRIENDLY_CATEGORIES = [9, 17, 21, 22, 27]

# Phrases that indicate the user is asking for a quiz/trivia question
QUIZ_REQUEST_PHRASES = (
    "quiz",
    "trivia",
    "ask me a question",
    "give me a question",
    "quiz me",
    "trivia question",
    "ask me something",
    "question for me",
    "give me a quiz",
    "give me a quiz question",
    "ask me a trivia question",
    "i want a question",
)


def user_asking_for_quiz(message: str) -> bool:
    """Return True if the message appears to be asking for a quiz or trivia question."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in QUIZ_REQUEST_PHRASES)


def _decode(text: str) -> str:
    """Decode HTML entities (e.g. &quot; &#039;) from Open Trivia DB."""
    if not text:
        return ""
    return html.unescape(text)


async def fetch_quiz_question(category_id: int | None = None) -> dict | None:
    """
    Fetch one easy multiple-choice question from Open Trivia DB.
    Returns dict with keys: question, correct_answer, incorrect_answers (list), category,
    or None on failure or rate limit.
    """
    params = {"amount": 1, "difficulty": "easy", "type": "multiple"}
    if category_id is not None:
        params["category"] = category_id
    else:
        params["category"] = random.choice(KID_FRIENDLY_CATEGORIES)
    try:
        async with httpx.AsyncClient(timeout=TRIVIA_REQUEST_TIMEOUT) as client:
            r = await client.get(OPENTDB_URL, params=params)
            r.raise_for_status()
            data = r.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
        logger.warning("Open Trivia DB request failed: %s", e)
        return None

    if not isinstance(data, dict):
        return None
    if data.get("response_code") != 0:
        logger.warning("Open Trivia DB returned response_code=%s", data.get("response_code"))
        return None
    results = data.get("results")
    if not results or not isinstance(results, list) or len(results) == 0:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    question = _decode(first.get("question") or "")
    correct = _decode(first.get("correct_answer") or "")
    incorrect_raw = first.get("incorrect_answers") or []
    incorrect = [_decode(str(a)) for a in incorrect_raw] if isinstance(incorrect_raw, list) else []
    category = _decode(first.get("category") or "Trivia")
    if not question or not correct:
        return None
    logger.info("Trivia question fetched: category=%s", category)
    return {
        "question": question,
        "correct_answer": correct,
        "incorrect_answers": incorrect,
        "category": category,
    }


def format_quiz_for_reply(data: dict) -> str:
    """Format a trivia question as a single reply string with options A) B) C) D)."""
    question = data["question"]
    correct = data["correct_answer"]
    incorrect = data.get("incorrect_answers") or []
    all_options = [correct] + incorrect
    random.shuffle(all_options)
    letters = ["A", "B", "C", "D"]
    parts = ["Here's a question! " + question]
    for i, opt in enumerate(all_options[:4]):
        if i < len(letters):
            parts.append(f"{letters[i]}) {opt}")
    return " ".join(parts)
