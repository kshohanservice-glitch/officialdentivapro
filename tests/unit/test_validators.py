import pytest
from dentiva.core.errors import ValidationError
from dentiva.core.validators import (
    validate_non_empty,
    validate_password_strength,
    validate_patient_code,
    validate_phone,
    validate_username,
)


def test_validate_non_empty_rejects_blank():
    with pytest.raises(ValidationError):
        validate_non_empty(" ", "name")
    assert validate_non_empty("  Alice  ", "n") == "Alice"


def test_validate_phone_accepts_bd_numbers():
    assert validate_phone("01712345678") == "01712345678"
    assert validate_phone("+8801712345678") == "+8801712345678"
    assert validate_phone("8801712345678") == "8801712345678"
    with pytest.raises(ValidationError):
        validate_phone("12345", required=True)


def test_validate_username_rejects_too_short():
    with pytest.raises(ValidationError):
        validate_username("ab")
    assert validate_username("Dr.Billu_99") == "dr.billu_99"


def test_validate_password_strength_min_length():
    with pytest.raises(ValidationError):
        validate_password_strength("123")
    assert validate_password_strength("secret1") == "secret1"


def test_validate_patient_code_uppercases():
    assert validate_patient_code("p-001") == "P-001"
    with pytest.raises(ValidationError):
        validate_patient_code("")
