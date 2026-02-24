"""
SQLite storage for profiles, summaries, and conversation history.
Uses crypto for optional encryption of sensitive columns.
"""

import copy
import json
import logging
import os
import re
import sqlite3

from fastapi import HTTPException

from crypto import decrypt_cell, encrypt_cell

logger = logging.getLogger(__name__)

# Paths: data folder lives under backend/
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
PROFILES_ROOT = os.path.join(DATA_DIR, "profiles")
DB_PATH = os.path.join(DATA_DIR, "kid_agent.db")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default


MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 100)
MAX_CACHED_PROFILES = _env_int("MAX_CACHED_PROFILES", 20)

_profile_cache: dict[str, dict] = {}
_summary_cache: dict[str, str] = {}
_history_cache: dict[str, list] = {}


def validate_profile_id(profile_id: str) -> None:
    """Reject invalid profile_id; raise 400 if invalid."""
    if not profile_id or len(profile_id) > 128:
        raise HTTPException(
            status_code=400,
            detail="profile_id is required and must be at most 128 characters",
        )
    if not re.match(r"^[a-zA-Z0-9\-_]+$", profile_id):
        raise HTTPException(
            status_code=400,
            detail="profile_id may only contain letters, digits, hyphens, underscores",
        )


def _evict_one_if_needed(cache: dict, new_key: str) -> None:
    if len(cache) >= MAX_CACHED_PROFILES and new_key not in cache and cache:
        cache.pop(next(iter(cache)), None)


def init_db() -> None:
    """Create data dir and SQLite tables if they do not exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT,
                interests TEXT
            );
            CREATE TABLE IF NOT EXISTS summaries (
                profile_id TEXT PRIMARY KEY,
                summary_text TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS history (
                profile_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (profile_id, seq)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def ensure_profile_dir(profile_id: str) -> None:
    """Ensure profile and summary rows exist in DB for this profile_id (insert defaults if missing)."""
    validate_profile_id(profile_id)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO profiles (profile_id, name, interests) VALUES (?, ?, ?)",
            (profile_id, None, "[]"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO summaries (profile_id, summary_text) VALUES (?, ?)",
            (profile_id, ""),
        )
        conn.commit()
    finally:
        conn.close()


def load_profile_json(profile_id: str) -> dict:
    """Load profile for this profile_id; return { name, interests } with defaults. Uses in-memory cache."""
    if profile_id in _profile_cache:
        return copy.deepcopy(_profile_cache[profile_id])
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT name, interests FROM profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            out = {"name": None, "interests": []}
        else:
            name_raw, interests_raw = row[0], row[1]
            name = decrypt_cell(name_raw)
            interests = []
            if interests_raw:
                try:
                    interests_json = decrypt_cell(interests_raw) or "[]"
                    interests = json.loads(interests_json)
                    if not isinstance(interests, list):
                        interests = []
                except (json.JSONDecodeError, TypeError):
                    pass
            out = {"name": name, "interests": interests}
        _evict_one_if_needed(_profile_cache, profile_id)
        _profile_cache[profile_id] = out
        return copy.deepcopy(out)
    finally:
        conn.close()


def save_profile_json(profile_id: str, data: dict) -> bool:
    """Write profile for this profile_id and update cache. Returns True on success."""
    ensure_profile_dir(profile_id)
    name_val = data.get("name")
    interests_json = json.dumps(data.get("interests") or [])
    name_stored = encrypt_cell(name_val if name_val is None else str(name_val))
    interests_stored = encrypt_cell(interests_json)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO profiles (profile_id, name, interests) VALUES (?, ?, ?)",
            (profile_id, name_stored, interests_stored),
        )
        conn.commit()
        _profile_cache[profile_id] = copy.deepcopy(data)
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save profile for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


def load_summary(profile_id: str) -> str:
    """Load summary for this profile_id; return empty string if missing. Uses in-memory cache."""
    if profile_id in _summary_cache:
        return _summary_cache[profile_id]
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT summary_text FROM summaries WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        raw = (row[0] or "").strip() if row else ""
        text = (decrypt_cell(raw) or "").strip()
        _evict_one_if_needed(_summary_cache, profile_id)
        _summary_cache[profile_id] = text
        return text
    finally:
        conn.close()


def save_summary(profile_id: str, text: str) -> bool:
    """Write summary for this profile_id and update cache. Returns True on success."""
    ensure_profile_dir(profile_id)
    stored = encrypt_cell(text or "") or ""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO summaries (profile_id, summary_text) VALUES (?, ?)",
            (profile_id, stored),
        )
        conn.commit()
        _summary_cache[profile_id] = text
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save summary for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


def load_history(profile_id: str) -> list[dict]:
    """Load last MAX_HISTORY_MESSAGES for this profile_id; list of { role, content }. Uses in-memory cache."""
    if profile_id in _history_cache:
        return copy.deepcopy(_history_cache[profile_id])
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT role, content FROM history
            WHERE profile_id = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (profile_id, MAX_HISTORY_MESSAGES),
        ).fetchall()
        out = []
        for role, content_raw in reversed(rows):
            content = decrypt_cell(content_raw) if content_raw else ""
            if role in ("user", "assistant") and isinstance(content, str):
                out.append({"role": role, "content": content})
        _evict_one_if_needed(_history_cache, profile_id)
        _history_cache[profile_id] = out
        return copy.deepcopy(out)
    finally:
        conn.close()


def save_history(profile_id: str, history: list[dict]) -> bool:
    """Replace history for this profile_id with the given list (last N only) and update cache."""
    ensure_profile_dir(profile_id)
    trimmed = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM history WHERE profile_id = ?", (profile_id,))
        for seq, entry in enumerate(trimmed, start=1):
            if (
                isinstance(entry, dict)
                and entry.get("role") in ("user", "assistant")
                and isinstance(entry.get("content"), str)
            ):
                content_stored = encrypt_cell(entry["content"]) or ""
                conn.execute(
                    "INSERT INTO history (profile_id, seq, role, content) VALUES (?, ?, ?, ?)",
                    (profile_id, seq, entry["role"], content_stored),
                )
        conn.commit()
        _history_cache[profile_id] = copy.deepcopy(trimmed)
        return True
    except sqlite3.Error as e:
        logger.exception("Failed to save history for profile_id=%s: %s", profile_id, e)
        return False
    finally:
        conn.close()


def invalidate_history_cache(profile_id: str) -> None:
    """Remove profile_id from history cache (e.g. after a failed save in stream)."""
    _history_cache.pop(profile_id, None)


def trim_history(history: list[dict]) -> list[dict]:
    """Return the last MAX_HISTORY_MESSAGES entries. Does not mutate in place."""
    if len(history) <= MAX_HISTORY_MESSAGES:
        return history
    return history[-MAX_HISTORY_MESSAGES:]
