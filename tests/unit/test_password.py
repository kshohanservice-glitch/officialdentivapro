from dentiva.auth.password import hash_password, needs_rehash, verify_password


def test_hash_and_verify_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_verify_empty_or_invalid_returns_false():
    assert not verify_password("", "")
    assert not verify_password("abc", "not-a-bcrypt-hash")


def test_needs_rehash_detects_low_rounds():
    import bcrypt
    salt = bcrypt.gensalt(rounds=4)
    weak = bcrypt.hashpw(b"abc", salt).decode("utf-8")
    assert needs_rehash(weak)
    assert not needs_rehash(hash_password("abc"))
