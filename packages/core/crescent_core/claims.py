from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class TokenClaims:
    """What products get after verifying an access token. Everything they need to
    make an authorization decision without touching identity's DB."""
    user_id: int
    email: str
    dept_id: int | None
    role: str | None
    token_version: int
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TokenClaims":
        return cls(
            user_id=int(payload["sub"]),
            email=payload.get("email", ""),
            dept_id=payload.get("dept_id"),
            role=payload.get("role"),
            token_version=int(payload.get("tv", 0)),
            raw=payload,
        )
