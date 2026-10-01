"""Machine fingerprinting for activation binding.

Uses a best-effort, privacy-respecting machine identifier built from
platform data. If none is available (e.g. locked-down Windows installs),
falls back to a per-installation UUID written into the config directory.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import uuid
from pathlib import Path

from dentiva.paths import paths

log = logging.getLogger(__name__)
MACHINE_ID_FILE = "machine.id"


def _windows_machine_guid() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,  # type: ignore[attr-defined]
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")  # type: ignore[attr-defined]
            return str(value).strip()
    except Exception as e:  # pragma: no cover - platform-specific
        log.debug("Unable to read MachineGuid: %s", e)
        return None


def _stored_uuid() -> str:
    paths.ensure()
    p: Path = paths.config_dir / MACHINE_ID_FILE
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        p.write_text(new_id, encoding="utf-8")
    except OSError as e:  # pragma: no cover
        log.warning("Unable to persist machine id: %s", e)
    return new_id


def machine_fingerprint() -> str:
    """Return a stable identifier for this machine (SHA-256 hex, 64 chars)."""
    parts = [
        platform.node(),
        platform.system(),
        platform.machine(),
        str(uuid.getnode()),
    ]
    guid = _windows_machine_guid()
    if guid:
        parts.append(guid)
    else:
        parts.append(_stored_uuid())
    blob = "|".join(str(p) for p in parts if p)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
