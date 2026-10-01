"""Common validation helpers used by setup wizard, forms, and services."""
from __future__ import annotations

import re

from .errors import ValidationError

# BD phone: optional +880 / 880 / 01 prefix, then 9-10 digits.
BD_PHONE_RE = re.compile(r"^(?:\+?880|0)1[3-9]\d{8}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,32}$")
PATIENT_CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,32}$")


def validate_non_empty(value: str, field: str, *, label: str | None = None) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationError(f"{label or field} is required.", field=field)
    return text


def validate_phone(value: str, field: str = "phone", *, required: bool = False) -> str:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError("Phone number is required.", field=field)
        return ""
    # Normalise visual separators users often type.
    digits = re.sub(r"[\s\-()]", "", text)
    if not BD_PHONE_RE.match(digits):
        raise ValidationError(
            "Invalid phone number. Use a Bangladesh mobile number, e.g. 017XXXXXXXX or +88017XXXXXXXX.",
            field=field,
        )
    return digits


def validate_email(value: str, field: str = "email", *, required: bool = False) -> str:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError("Email is required.", field=field)
        return ""
    if not EMAIL_RE.match(text):
        raise ValidationError("Invalid email address.", field=field)
    return text.lower()


def validate_username(value: str) -> str:
    text = (value or "").strip()
    if not USERNAME_RE.match(text):
        raise ValidationError(
            "Username must be 3-32 characters using letters, numbers, '_' or '.'.",
            field="username",
        )
    return text.lower()


def validate_password_strength(value: str) -> str:
    if not value or len(value) < 6:
        raise ValidationError(
            "Password must be at least 6 characters long.", field="password"
        )
    if len(value) > 256:
        raise ValidationError("Password is too long.", field="password")
    return value


def validate_patient_code(value: str) -> str:
    text = (value or "").strip().upper()
    if not PATIENT_CODE_RE.match(text):
        raise ValidationError(
            "Patient code must be 2-32 characters using letters, numbers or '-'.",
            field="patient_code",
        )
    return text


def validate_positive_int(value: int, field: str, *, label: str | None = None, zero_ok: bool = False) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label or field} must be a whole number.", field=field)
    if zero_ok:
        if iv < 0:
            raise ValidationError(f"{label or field} cannot be negative.", field=field)
    else:
        if iv <= 0:
            raise ValidationError(f"{label or field} must be a positive number.", field=field)
    return iv
