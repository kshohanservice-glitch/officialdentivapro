"""Obfuscated activation salt split.

The activation secret is derived from two halves XOR'd together. This is
deliberately not cryptographically unbreakable (no offline scheme can be);
it is a reasonable commercial-grade deterrent against casual key
extraction from binary strings.
"""
from __future__ import annotations

# Two seemingly-random byte arrays. At runtime they are XOR'd to produce the
# per-app HMAC salt. These values are generated from /dev/urandom and do not
# themselves contain the activation code.
_SALT_A = bytes.fromhex(
    "9ac6f0314b2d5e6a817c0d4e7b25af08"
    "1d6f8392be557cc83e9f0d62a144b8d7"
    "c31f46bb93a8e06c7d18af25eb99"
)
_SALT_B = bytes.fromhex(
    "2c0db1f3d4658a720bc1758a226ca419"
    "c2a1f1b4dd0bc3da153ca941d693d426"
    "b4e9c50be8cd32208ad33968592b"
)


def derived_salt() -> bytes:
    return bytes(a ^ b for a, b in zip(_SALT_A, _SALT_B, strict=False))
