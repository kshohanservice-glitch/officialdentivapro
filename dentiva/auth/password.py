"""Password hashing with bcrypt.

Uses a configurable work factor (default 12). Each hash is self-describing
(contains salt, work factor, algorithm), so the cost can be raised over time
by re-hashing on next successful login.
"""
from __future__ import annotations

import bcrypt

DEFAULT_ROUNDS = 12


def hash_password(plaintext: str, rounds: int = DEFAULT_ROUNDS) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("Password must be a non-empty string.")
    if len(plaintext) > 72:
        # bcrypt only uses the first 72 bytes. We reject overly long passwords
        # rather than silently truncating.
        raise ValueError("Password must be at most 72 characters.")
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, stored_hash: str) -> bool:
    if not plaintext or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(stored_hash: str, rounds: int = DEFAULT_ROUNDS) -> bool:
    """Return True if the stored hash uses a lower work factor than current."""
    try:
        # bcrypt hash format: $2b$<rounds>$<salt+hash>
        parts = stored_hash.split("$")
        if len(parts) < 3:
            return True
        existing_rounds = int(parts[2])
        return existing_rounds < rounds
    except (ValueError, IndexError, AttributeError):
        return True
