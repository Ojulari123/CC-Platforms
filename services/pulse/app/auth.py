"""How Pulse knows who's calling.

Tokens are minted by identity and verified here *locally* against identity's
published public keys — Pulse never calls identity to check a token, and never
touches identity's database (CLAUDE.md rules 2–4). All of the verification logic
lives in the shared `crescent_core` package so Pulse and Forge stay in step.

`current_user` yields a `TokenClaims`: user_id, email, per-department role,
per-department team, the teams they lead, and platform-admin. Every
authorization decision in Pulse is made from that — see app/services/reports.py.
"""
from crescent_core import JWKSClient, current_user_dep
from app.config import settings

jwks_client = JWKSClient(settings.IDENTITY_JWKS_URL, ttl_seconds=settings.JWKS_TTL_SECONDS)

# One dependency, wired once, reused by every protected endpoint.
current_user = current_user_dep(jwks_client, issuer=settings.JWT_ISSUER)
