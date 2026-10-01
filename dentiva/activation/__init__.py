"""Offline activation subsystem.

The fixed activation code is **never** stored as a literal in source. It is
verified via HMAC-SHA256 against an embedded expected digest. The salt and
digest are split across two helper modules to make casual binary scanning
ineffective.

On success, a per-machine activation record (HMAC'd) is written to
``<config>/activation.dat``. Subsequent launches verify that file before
allowing the application to start.
"""
from . import verifier  # noqa: F401  (re-export for callers who use dentiva.activation.verifier)
