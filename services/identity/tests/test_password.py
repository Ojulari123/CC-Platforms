import pytest
from fastapi import HTTPException
from app.security.password import hash_password, validate_password, verify_password

def test_hash_and_verify_roundtrip():
    hashed = hash_password("Correct1!horse")
    assert hashed != "Correct1!horse"
    assert verify_password("Correct1!horse", hashed) is True
    assert verify_password("wrong-password", hashed) is False

def test_hash_produces_different_outputs_for_same_input():
    assert hash_password("Same1!password") != hash_password("Same1!password")

@pytest.mark.parametrize("password", ["Shor1!", "alllowercase1!", "ALLUPPERCASE1!", "NoNumbers!", "NoSpecial1"])
def test_validate_rejects_weak_passwords(password):
    with pytest.raises(HTTPException) as exc:
        validate_password(password)
    assert exc.value.status_code == 400

def test_validate_accepts_strong_password():
    assert validate_password("Strong1!password") == "Strong1!password"
