"""Activation verification.

Workflow:

1. ``is_activated()`` checks for a valid activation file.
2. ``activate(code, fingerprint)`` validates a user-entered code and writes
   the activation record.
3. Activation records are HMAC'd with a per-machine key derived from the
   machine fingerprint + embedded pepper, making copied activation.dat
   files invalid on other machines.

The activation code itself is verified against the embedded HMAC-SHA256
expected digest using :func:`hmac.compare_digest` — no plaintext comparison.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from dentiva.core.errors import ActivationError
from dentiva.paths import paths

from ._digest import expected_digest_hex
from ._salt import derived_salt
from .machine import machine_fingerprint

log = logging.getLogger(__name__)
ACTIVATION_FILE = "activation.dat"
PEPPER = "dentiva-pro-v1-activation-record"


def _activation_path() -> Path:
    paths.ensure()
    return paths.config_dir / ACTIVATION_FILE


def _record_mac(record: dict, fingerprint: str) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    key_material = (PEPPER + "|" + fingerprint).encode("utf-8")
    return hmac.new(key_material, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_code(code: str) -> str:
    return (code or "").strip().replace("-", "").replace(" ", "")


def _code_matches(code: str) -> bool:
    normalized = _normalize_code(code)
    if not normalized:
        return False
    salt = derived_salt()
    computed = hmac.new(salt, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected_digest_hex())


def is_activated() -> bool:
    """Return True iff a valid activation record exists for this machine."""
    p = _activation_path()
    if not p.exists():
        return False
    try:
        raw = p.read_text(encoding="utf-8")
        record = json.loads(raw)
        fp = machine_fingerprint()
        mac = record.pop("mac", None)
        if not mac:
            return False
        expected = _record_mac(record, fp)
        if not hmac.compare_digest(mac, expected):
            log.warning("Activation record MAC mismatch (tampered or copied).")
            return False
        if record.get("product") != "dentiva-pro":
            return False
        return True
    except (OSError, ValueError, TypeError) as e:
        log.warning("Failed to read activation record: %s", e)
        return False


def activate(code: str) -> None:
    """Validate ``code`` and persist an activation record.

    Raises :class:`ActivationError` on failure.
    """
    normalized = _normalize_code(code)
    if not _code_matches(normalized):
        raise ActivationError(
            "Invalid activation code. Please enter the code provided with your license.",
            detail="code_mismatch",
        )
    fp = machine_fingerprint()
    record = {
        "product": "dentiva-pro",
        "activated_at": int(time.time()),
        "fingerprint": fp[:16],
        "version": 1,
    }
    record["mac"] = _record_mac(record, fp)
    p = _activation_path()
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        raise ActivationError(
            "Could not save activation file. Please check that Dentiva Pro has permission to write to its data folder.",
            detail=str(e),
        )
    log.info("Activation successful.")


def clear_activation() -> None:
    """Remove the activation record (for support / reset flows)."""
    p = _activation_path()
    try:
        if p.exists():
            p.unlink()
    except OSError as e:  # pragma: no cover
        log.warning("Failed to clear activation: %s", e)
