"""Expected HMAC-SHA256 digest of the activation code.

The 64-char hex digest is stored as 4 chunks and reversed at runtime to
defeat the laziest string-scanning attacks. See :mod:`dentiva.activation.verifier`.
"""
from __future__ import annotations

# The four 16-char chunks of the HMAC-SHA256 hex digest, stored reversed.
# verifier.expected_digest_hex() reverses and joins.
_DIGEST_PARTS_REVERSED = [
    "c7ef028f66fc1552",
    "52c731a408fb21ab",
    "44ffcee1b23e63f0",
    "e6c1445326d3a131",
]


def expected_digest_hex() -> str:
    return "".join(reversed(_DIGEST_PARTS_REVERSED))
