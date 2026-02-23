"""
Optional encryption at rest for sensitive DB columns.
Set KID_AGENT_DB_KEY to a Fernet key (e.g. from Fernet.generate_key()).
Losing the key means encrypted data cannot be decrypted.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)
_DB_KEY_ENV = "KID_AGENT_DB_KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    """Return Fernet instance if KID_AGENT_DB_KEY is set and valid; else None (no encryption)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key_b64 = os.environ.get(_DB_KEY_ENV)
    if not key_b64 or not (key_b64 if isinstance(key_b64, str) else b"").strip():
        return None
    key_bytes = key_b64.strip().encode() if isinstance(key_b64, str) else key_b64
    try:
        _fernet = Fernet(key_bytes)
        return _fernet
    except Exception:
        logger.warning(
            "Invalid %s; running without encryption. Generate a key with: Fernet.generate_key()",
            _DB_KEY_ENV,
        )
        return None


def encrypt_cell(plain: str | None) -> str | None:
    """Encrypt a string for storage; return plaintext if encryption is disabled or plain is empty."""
    if plain is None or plain == "":
        return plain
    f = _get_fernet()
    if f is None:
        return plain
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_cell(cipher: str | None) -> str | None:
    """Decrypt a stored value; if decrypt fails (e.g. legacy plaintext), return as-is."""
    if cipher is None or cipher == "":
        return cipher
    f = _get_fernet()
    if f is None:
        return cipher
    try:
        return f.decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return cipher
