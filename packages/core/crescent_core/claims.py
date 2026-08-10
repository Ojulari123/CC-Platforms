from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class DeptMembership:
    dept_id: int
    team_id: int | None
    role: str

@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    email: str
    memberships: tuple[DeptMembership, ...]
    is_platform_admin: bool
    token_version: int
    raw: dict[str, Any]
    leads: tuple[int, ...] = ()

    def role_in(self, dept_id: int) -> str | None:
        """The caller's role in one department, or None if they're not in it."""
        for m in self.memberships:
            if m.dept_id == dept_id:
                return m.role
        return None

    def is_member_of(self, dept_id: int) -> bool:
        return self.role_in(dept_id) is not None

    def team_in(self, dept_id: int) -> int | None:
        for m in self.memberships:
            if m.dept_id == dept_id:
                return m.team_id
        return None

    def leads_team(self, team_id: int) -> bool:
        return team_id in self.leads

    @property
    def dept_ids(self) -> tuple[int, ...]:
        return tuple(m.dept_id for m in self.memberships)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TokenClaims":
        raw_memberships = payload.get("memberships") or []
        return cls(
            user_id=int(payload["sub"]),
            email=payload.get("email", ""),
            memberships=tuple(
                DeptMembership(
                    dept_id=int(m["dept_id"]),
                    team_id=m.get("team_id"),
                    role=m.get("role", ""),
                )
                for m in raw_memberships
                if m.get("dept_id") is not None
            ),
            is_platform_admin=bool(payload.get("is_platform_admin", False)),
            token_version=int(payload.get("tv", 0)),
            leads=tuple(int(t) for t in (payload.get("leads") or [])),
            raw=payload,
        )
