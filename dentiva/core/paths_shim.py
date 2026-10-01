"""Tiny re-export that avoids circular imports at logging bootstrap time.

The logging module is needed before the full :mod:`dentiva` package is
importable in some frozen / bootstrapping situations; this module provides
a safe, lightweight import path to the resolved :data:`paths` singleton.
"""
from __future__ import annotations

from dentiva.paths import paths  # noqa: F401
