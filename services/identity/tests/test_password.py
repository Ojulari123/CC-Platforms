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


class TestBcryptLengthLimit:
    """bcrypt reads only the first 72 bytes and ignores the rest, silently.
    Before the cap, a 103-character password could be logged into with just its
    first 72 characters while the API advertised a 128-character limit."""

    def test_password_over_72_bytes_is_rejected(self):
        with pytest.raises(HTTPException) as e:
            validate_password("Aa1!" + "x" * 80)
        assert e.value.status_code == 400
        assert "too long" in e.value.detail

    def test_exactly_72_bytes_is_allowed(self):
        pw = "Aa1!" + "x" * 68
        assert len(pw.encode()) == 72
        assert validate_password(pw) == pw

    def test_multibyte_characters_count_as_their_byte_length(self):
        """'é' is 2 bytes, so 40 of them exceed the limit at only 44 characters."""
        pw = "Aa1!" + "é" * 40
        assert len(pw) == 44 and len(pw.encode()) > 72
        with pytest.raises(HTTPException) as e:
            validate_password(pw)
        assert "too long" in e.value.detail

    def test_the_api_rejects_an_over_long_password(self, client):
        r = client.post("/auth/register", json={
            "email": "long@example.com", "password": "Aa1!" + "x" * 80,
            "first_name": "L", "last_name": "P", "dept_name": "Eng",
        })
        assert r.status_code == 422  # schema catches it before the service does

    def test_no_truncated_password_can_log_in(self, client, registered_user, invite_user):
        """The actual vulnerability: the first 72 bytes must not be a valid
        password for an account created with a longer one."""
        dept = registered_user["dept_id"]
        long_pw = "Aa1!" + "x" * 68  # exactly 72 — the longest we now accept
        u = invite_user(registered_user["tokens"], dept, "long@example.com", "engineer", password=long_pw)
        assert u  # accepted
        # A shorter prefix must not work.
        r = client.post("/auth/login", json={"email": "long@example.com", "password": long_pw[:60]})
        assert r.status_code == 401
