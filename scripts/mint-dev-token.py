#!/usr/bin/env python
"""Mint an identity access token for LOCAL TESTING ONLY.

Signs a token with identity's private key exactly the way identity does, so you
can call Pulse (which verifies tokens against identity's public JWKS) without
going through register → invite → accept for every test user. The dept/team ids
in the token are just claims — Pulse trusts them, so they don't need to exist in
identity's database for you to exercise Pulse.

DO NOT use outside local development.

Run it from services/identity (so it finds that service's .env and keys/):

    cd services/identity

    # an engineer on team 3 in department 1:
    python ../../scripts/mint-dev-token.py --user-id 10 --membership 1:3:engineer

    # the LEAD of team 3 (role manager AND leads=[3]):
    python ../../scripts/mint-dev-token.py --user-id 20 --membership 1:3:manager --leads 3

    # a department admin (no team):
    python ../../scripts/mint-dev-token.py --user-id 30 --membership 1::admin

    # a platform admin:
    python ../../scripts/mint-dev-token.py --user-id 99 --platform-admin
"""
import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument(
        "--membership", action="append", default=[], metavar="DEPT:TEAM:ROLE",
        help="e.g. 1:3:engineer  (blank team is fine: 1::admin). Repeat for multiple departments.",
    )
    parser.add_argument("--leads", default="", help="comma-separated team ids this user is the named lead of")
    parser.add_argument("--platform-admin", action="store_true")
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

    token = create_access_token(
        user_id=args.user_id,
        email=args.email or f"user{args.user_id}@example.com",
        memberships=memberships,
        is_platform_admin=args.platform_admin,
        token_version=0,
        leads=leads,
    )
    print(token)


if __name__ == "__main__":
    main()
