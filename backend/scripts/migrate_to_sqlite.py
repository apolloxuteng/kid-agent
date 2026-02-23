#!/usr/bin/env python3
"""
One-time migration: copy data from data/profiles/{profile_id}/ (profile.json, summary.txt, history.json)
into the SQLite database (data/kid_agent.db).

Run from the backend directory:
  python scripts/migrate_to_sqlite.py
  # or: ./venv/bin/python scripts/migrate_to_sqlite.py
"""

import json
import os
import sys

# Ensure backend root is on path so we can import server
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _backend_dir)

from server import (
    DATA_DIR,
    PROFILES_ROOT,
    init_db,
    save_profile_json,
    save_summary,
    save_history,
)


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db()

    if not os.path.isdir(PROFILES_ROOT):
        print("No profiles directory found. Nothing to migrate.")
        return

    migrated = 0
    for name in os.listdir(PROFILES_ROOT):
        path = os.path.join(PROFILES_ROOT, name)
        if not os.path.isdir(path):
            continue
        profile_id = name

        profile = {"name": None, "interests": []}
        profile_path = os.path.join(path, "profile.json")
        if os.path.isfile(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile["name"] = data.get("name")
                interests = data.get("interests", [])
                profile["interests"] = interests if isinstance(interests, list) else []
            except (json.JSONDecodeError, OSError):
                pass

        summary = ""
        summary_path = os.path.join(path, "summary.txt")
        if os.path.isfile(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = f.read().strip()
            except OSError:
                pass

        history = []
        history_path = os.path.join(path, "history.json")
        if os.path.isfile(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    history = [
                        e
                        for e in data
                        if isinstance(e, dict)
                        and e.get("role") in ("user", "assistant")
                        and isinstance(e.get("content"), str)
                    ]
            except (json.JSONDecodeError, OSError):
                pass

        save_profile_json(profile_id, profile)
        save_summary(profile_id, summary)
        save_history(profile_id, history)
        migrated += 1
        print(f"Migrated profile_id={profile_id}")

    print(f"Done. Migrated {migrated} profile(s).")


if __name__ == "__main__":
    main()
