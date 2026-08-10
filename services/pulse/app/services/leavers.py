"""Dropping the stored GitHub credentials of people who have left.

Identity can't tell Pulse when it deactivates someone — a product being pushed at by
identity is exactly the coupling the architecture rules forbid. So Pulse asks. It
already resolves user_ids to profiles through identity's internal endpoint, and that
answer carries `is_active`, so the same channel is what notices a leaver. Nothing new
is opened, and identity's database is never read.

Only the live credential goes. Commits, pull requests, reviews and issues stay exactly
as they are, still attributed: a report covering a past week has to keep adding up
after the author leaves, and attribution is history rather than a live permission.

A hard-deleted user has no profile to carry is_active, so identity names them
separately in unknown_user_ids. Both count as departed here, for the same reason:
the credential belongs to someone who is gone.

The failure mode this file exists to avoid: reading "identity didn't answer" as
"everyone left". It never infers departure from absence — only from something
identity said, either is_active=False or an id listed as unknown. A chunk identity
failed to answer contributes to neither, so an outage (total or partial) can't
delete a row.
"""
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import GitHubAccount
from app.services.identity_client import resolve_profiles_answer

logger = logging.getLogger(__name__)

def revoke_departed_credentials(db: Session) -> list[int]:
    """Delete the GitHubAccount of every connected user identity reports as inactive
    or as unknown (deleted). Returns the user_ids whose credentials were dropped,
    oldest id first."""
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
