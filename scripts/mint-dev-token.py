#!/usr/bin/env python
"""Mint an identity access token for LOCAL TESTING ONLY.

Signs a token with identity's private key exactly the way identity does, so you
can call Pulse (which verifies tokens against identity's public JWKS) without
going through register → invite → accept for every test user. The dept/team ids
in the token are just claims — Pulse trusts them, so they don't need to exist in
identity's database for you to exercise Pulse.

DO NOT use outside local development.

Two claims are NOT free-form, because identity checks them against the database row
instead of trusting the token:

  tv (token version)  identity rejects the token with 401 "Session revoked" unless it
                      matches the user's current token_version, which every password
                      reset and logout-everywhere bumps. So this script asks the
                      RUNNING identity for the real value (see --identity-url) rather
                      than guessing. --token-version overrides the lookup.

  is_platform_admin   require_platform_admin reads users.is_platform_admin off the row,
                      so --platform-admin on a user id that is not actually a platform
                      admin still gets 403. The flag only helps for a user who already
                      has the bit set (or for services that trust the claim).

Everything else (dept/team ids, roles, leads) is just a claim: Pulse and Forge trust it,
so those ids do not need to exist in identity's database to exercise those services.

Run it from services/identity (so it finds that service's .env and keys/):

    cd services/identity

    # an engineer on team 3 in department 1:
    python ../../scripts/mint-dev-token.py --user-id 10 --membership 1:3:engineer

    # the LEAD of team 3 (role manager AND leads=[3]):
    python ../../scripts/mint-dev-token.py --user-id 20 --membership 1:3:manager --leads 3

    # a department admin (no team):
    python ../../scripts/mint-dev-token.py --user-id 30 --membership 1::admin

    # a platform admin (only works if user 1 really has is_platform_admin set):
    python ../../scripts/mint-dev-token.py --user-id 1 --platform-admin

    # identity is not running, or is somewhere else:
    python ../../scripts/mint-dev-token.py --user-id 1 --token-version 4
"""
import argparse
import os
import sys

DEFAULT_IDENTITY_URL = "http://localhost:8001"

def lookup_token_version(identity_url: str, user_id: int) -> int | None:
    """Ask the running identity for the user's current token_version. Uses a
    self-minted service token: this script already holds the signing key, and the
    endpoint only wants the tokens:verify scope. Going through identity (rather than
    the database) means it reads whatever database that identity is actually pointed
    at — in Compose that is the sandbox Postgres, not the .env URL. Returns None when
    identity is unreachable or does not know the user."""
    import httpx
    from app.security.jwt import create_service_token

    token = create_service_token(client_id="dev-mint-script", scopes="tokens:verify")
    try:
        response = httpx.post(
            f"{identity_url.rstrip('/')}/internal/users/token-versions",
            json={"user_ids": [user_id]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError as exc:
        print(f"warning: could not reach identity at {identity_url} ({exc.__class__.__name__}).", file=sys.stderr)
        return None
    if response.status_code != 200:
        print(f"warning: identity returned {response.status_code} for the token_version lookup.", file=sys.stderr)
        return None
    for entry in response.json().get("users", []):
        if int(entry["user_id"]) == user_id:
            return int(entry["token_version"])
    print(f"warning: identity does not have a user {user_id}.", file=sys.stderr)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument(
        "--membership", action="append", default=[], metavar="DEPT:TEAM:ROLE",
        help="e.g. 1:3:engineer  (blank team is fine: 1::admin). Repeat for multiple departments.",
    )
    parser.add_argument("--leads", default="", help="comma-separated team ids this user is the named lead of")
    parser.add_argument(
        "--platform-admin", action="store_true",
        help="set the is_platform_admin claim. Identity's own admin endpoints still read the flag off the "
             "user row, so this alone does not make a non-admin user id an admin there.",
    )
    parser.add_argument(
        "--token-version", type=int, default=None, metavar="N",
        help="skip the lookup and use this tv claim. Use when identity is not running; a value below the "
             "user's current token_version gets 401 'Session revoked' from identity.",
    )
    parser.add_argument(
        "--identity-url", default=DEFAULT_IDENTITY_URL,
        help=f"running identity to read the current token_version from (default: {DEFAULT_IDENTITY_URL})",
    )
    args = parser.parse_args()

    # config.py requires DATABASE_URL, but minting a token never touches the DB.
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost/unused")
    sys.path.insert(0, os.getcwd())  # so `app` imports when run from services/identity

    try:
        from app.security import create_access_token
    except ModuleNotFoundError:
        sys.exit("Run this from inside services/identity (so `app` and keys/ are found).")

    memberships = []
    for spec in args.membership:
        parts = spec.split(":")
        dept_id = int(parts[0])
        team_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
        role = parts[2] if len(parts) > 2 and parts[2] else "engineer"
        memberships.append({"dept_id": dept_id, "team_id": team_id, "role": role})

    leads = [int(x) for x in args.leads.split(",") if x.strip()]

    if args.token_version is not None:
        token_version = args.token_version
    else:
        token_version = lookup_token_version(args.identity_url, args.user_id)
        if token_version is None:
            # 0 is right for the made-up user ids used to exercise Pulse/Forge, and wrong
            # for a real user whose tv has moved — say so instead of printing a dud token.
            print("warning: falling back to tv=0. Fine for a user id that only exists as a claim; "
                  "identity will answer 401 'Session revoked' for a real user past tv 0. "
                  "Pass --token-version to set it.", file=sys.stderr)
            token_version = 0

    token = create_access_token(
        user_id=args.user_id,
        email=args.email or f"user{args.user_id}@example.com",
        memberships=memberships,
        is_platform_admin=args.platform_admin,
        token_version=token_version,
        leads=leads,
    )
    print(token)


if __name__ == "__main__":
    main()
