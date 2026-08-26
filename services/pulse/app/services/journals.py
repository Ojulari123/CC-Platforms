import logging
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.config import settings
from app.models import LLM_KIND_JOURNAL_ROLLUP, JournalRollup, LlmUsage, RepoJournal, Repository
from app.services import ai_provider, credentials, journal_prompts, llm_budget, persona_prompts, personas, repositories as repo_service

logger = logging.getLogger(__name__)

# One rollup reads at most this many entries. The count sent to the model stays exact
# and the payload is flagged when older entries were left out.
_MAX_ROLLUP_ENTRIES = 50

class NoJournalEntriesError(Exception):
    pass

def _readable_repo(db: Session, user: TokenClaims, repo_id: int) -> Repository:
    # get_repository 404s (not 403s) on a repo the caller can't see, so a journal URL
    # can't be used to confirm a private repo exists either.
    return repo_service.get_repository(db, user, repo_id)

def _writable_repo(db: Session, user: TokenClaims, repo_id: int) -> Repository:
    repo = _readable_repo(db, user, repo_id)
    if not repo_service.may_write_on_repo(db, user, repo):
        raise HTTPException(
            status_code=403,
            detail=(
                "You need to be a member of this repository to post to its journal. "
                "Membership means you lead it, deputise on it, administer its department, "
                "or have synced GitHub activity in it."
            ),
        )
    return repo

def _get_journal(db: Session, repo_id: int, journal_id: int) -> RepoJournal:
    journal = db.get(RepoJournal, journal_id)
    if not journal or journal.repo_id != repo_id:
        raise HTTPException(status_code=404, detail="Journal entry not found in this repository")
    return journal

def list_journals(db: Session, user: TokenClaims, repo_id: int, *, limit: int, offset: int) -> tuple[list[RepoJournal], int]:
    repo = _readable_repo(db, user, repo_id)
    base = select(RepoJournal).where(RepoJournal.repo_id == repo.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(RepoJournal.created_at.desc(), RepoJournal.id.desc()).limit(limit).offset(offset))
    return list(rows), total

def create_journal(db: Session, user: TokenClaims, repo_id: int, body: str) -> RepoJournal:
    repo = _writable_repo(db, user, repo_id)
    journal = RepoJournal(repo_id=repo.id, author_user_id=user.user_id, body=body)
    db.add(journal)
    db.commit()
    db.refresh(journal)
    return journal

def update_journal(db: Session, user: TokenClaims, repo_id: int, journal_id: int, body: str) -> RepoJournal:
    repo = _readable_repo(db, user, repo_id)
    journal = _get_journal(db, repo.id, journal_id)
    if journal.author_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own journal entry")
    journal.body = body
    journal.edited_at = func.now()
    db.commit()
    db.refresh(journal)
    return journal

def delete_journal(db: Session, user: TokenClaims, repo_id: int, journal_id: int) -> None:
    repo = _readable_repo(db, user, repo_id)
    journal = _get_journal(db, repo.id, journal_id)
    if journal.author_user_id != user.user_id and not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="You can only delete your own journal entry")
    db.delete(journal)
    db.commit()

def _recent_entries(db: Session, repo_id: int) -> list[RepoJournal]:
    """Newest first out of the database so the cap keeps the most recent entries, then
    reversed: a progress readout only makes sense read in the order it happened."""
    q = select(RepoJournal).where(RepoJournal.repo_id == repo_id).order_by(RepoJournal.created_at.desc(), RepoJournal.id.desc())
    rows = list(db.scalars(q.limit(_MAX_ROLLUP_ENTRIES)))
    return list(reversed(rows))

def _rollup_payload(repo: Repository, entries: list[RepoJournal], total: int) -> dict:
    return {
        "repo": repo.full_name,
        "entry_count": total,
        "truncated": total > len(entries),
        "entries": [
            {"author_user_id": e.author_user_id, "created_at": e.created_at, "body": e.body}
            for e in entries
        ],
    }

def generate_rollup(db: Session, user: TokenClaims, repo_id: int, persona_id: int | None = None) -> JournalRollup:
    repo = _writable_repo(db, user, repo_id)
    entries = _recent_entries(db, repo.id)
    if not entries:
        raise NoJournalEntriesError(
            "This repository's journal is empty, so there is nothing to summarise yet."
        )
    total = db.scalar(select(func.count()).select_from(RepoJournal).where(RepoJournal.repo_id == repo.id)) or 0

    payload = _rollup_payload(repo, entries, total)
    persona = personas.resolve(db, user, persona_id)
    credential = credentials.resolve_credential(db, user)
    system_prompt = persona_prompts.apply_to_system_prompt(journal_prompts.build_system_prompt(), persona)
    user_prompt = journal_prompts.build_user_prompt(payload)
    llm_budget.check_budget(
        db, user.user_id, kind=LLM_KIND_JOURNAL_ROLLUP, credential=credential, dept_ids=user.dept_ids, is_platform_admin=user.is_platform_admin,
        estimated_tokens=llm_budget.estimate_tokens([system_prompt, user_prompt]) + settings.AI_MAX_OUTPUT_TOKENS,
    )
    result = ai_provider.generate(
        system_prompt,
        user_prompt,
        max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        credential=credential,
    )
    logger.info(
        "generate_rollup: user=%s repo=%s entries=%s persona=%s key=%s model=%s tokens=%s truncated=%s",
        user.user_id, repo.id, len(entries), persona.id,
        credential.source if credential else "none", result.model, result.token_count, payload["truncated"],
    )

    rollup = JournalRollup(
        repo_id=repo.id,
        summary=result.text,
        entry_count=len(entries),
        covers_from=entries[0].created_at,
        covers_to=entries[-1].created_at,
        generated_by_user_id=user.user_id,
        model=result.model,
        prompt_version=journal_prompts.PROMPT_VERSION,
    )
    db.add(rollup)
    # Same transaction as the rollup, for the reason generation.py spells out: a second
    # commit means a failed ledger write 500s work that was already saved, so the caller
    # retries and pays for another generation.
    db.flush()
    db.add(LlmUsage(report_id=None, kind=LLM_KIND_JOURNAL_ROLLUP, user_id=user.user_id, tokens=result.token_count or 0))
    db.commit()
    db.refresh(rollup)
    return rollup

def latest_rollup(db: Session, user: TokenClaims, repo_id: int) -> JournalRollup | None:
    """None when the repository is readable and simply has no rollup yet.

    The 404 that used to stand in for that is gone, and deliberately. It meant two
    different things at once, "there is no rollup" and "you cannot see this repository",
    and the caller had no way to tell which. _readable_repo still raises 404 for the
    second, so the two are now distinguishable: 404 means the repository, None means the
    rollup.
    """
    repo = _readable_repo(db, user, repo_id)
    return db.scalar(
        select(JournalRollup)
        .where(JournalRollup.repo_id == repo.id)
        .order_by(JournalRollup.created_at.desc(), JournalRollup.id.desc())
        .limit(1)
    )
