"""Dropping the stored GitHub credentials of people who have left.

The failure mode this file exists to avoid: reading "identity didn't answer" as
"everyone left". Departure is only ever inferred from something identity said —
is_active=False, or an id it listed as unknown (hard-deleted). A chunk identity failed
to answer contributes to neither, so an outage (total or partial) can't delete a row.

Only the live credential goes: commits, pull requests, reviews and issues stay
attributed, because a report covering a past week has to keep adding up afterwards.
"""
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import GitHubAccount
from app.services.identity_client import resolve_profiles_answer

logger = logging.getLogger(__name__)

def revoke_departed_credentials(db: Session) -> list[int]:
    accounts = {a.user_id: a for a in db.scalars(select(GitHubAccount))}
    if not accounts:
        return []

    answer = resolve_profiles_answer(sorted(accounts))
    if not answer.profiles and not answer.unknown:
        logger.warning("leaver check skipped: identity answered for none of %d connected account(s)", len(accounts))
        return []

    departed = [uid for uid in sorted(accounts)
                if uid in answer.unknown or answer.profiles.get(uid, {}).get("is_active") is False]
    if not departed:
        return []
    for uid in departed:
        db.delete(accounts[uid])
    db.commit()
    logger.info("revoked stored GitHub credentials for departed user(s): %s", ", ".join(str(u) for u in departed))
    return departed
