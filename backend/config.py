"""
Shared env-derived configuration. Single place for _env_int and int constants
used by server, llm, and db.
"""

import os


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


# Server (profile extraction)
MAX_INTERESTS = _env_int("MAX_INTERESTS", 10)
MAX_EXTRACTED_LENGTH = _env_int("MAX_EXTRACTED_LENGTH", 80)

# LLM
OLLAMA_CHAT_TIMEOUT = _env_int("OLLAMA_CHAT_TIMEOUT", 60)
OLLAMA_SUMMARY_TIMEOUT = _env_int("OLLAMA_SUMMARY_TIMEOUT", 30)
RECENT_MESSAGES_COUNT = _env_int("RECENT_MESSAGES_COUNT", 10)

# DB
MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 100)
MAX_CACHED_PROFILES = _env_int("MAX_CACHED_PROFILES", 20)
