"""Personas are per-user, plus a handful of read-only presets everyone can see.

Permissions live here rather than in the router, and someone else's persona is a 404,
not a 403 — the same choice repositories.get_repository makes, for the same reason: a
403 confirms the row exists.
"""
from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from crescent_core import TokenClaims
from app.models import DEFAULT_SYSTEM_PERSONA, PERSONA_SYSTEM_PRESETS, Persona

def _get(db: Session, persona_id: int) -> Persona:
    persona = db.get(Persona, persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona

def _readable(db: Session, user: TokenClaims, persona_id: int) -> Persona:
    persona = _get(db, persona_id)
    if persona.owner_user_id is not None and persona.owner_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona

def _writable(db: Session, user: TokenClaims, persona_id: int) -> Persona:
    persona = _readable(db, user, persona_id)
    if persona.owner_user_id is None:
        # Visible to the caller, so 403 rather than 404: there is nothing to hide, and a
        # 404 here would read as "your persona vanished".
        raise HTTPException(status_code=403, detail="Built-in personas can't be edited. Copy one into your own instead.")
    return persona

def seed_system_presets(db: Session) -> list[Persona]:
    """Idempotent. The presets are seeded by migration 0011 in production; this exists
    for a database that was created straight from the models."""
    rows = []
    for preset in PERSONA_SYSTEM_PRESETS:
        existing = db.scalar(select(Persona).where(Persona.owner_user_id.is_(None), Persona.name == preset["name"]))
        if existing is None:
            existing = Persona(owner_user_id=None, is_default=False, **preset)
            db.add(existing)
        rows.append(existing)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows

def list_personas(db: Session, user: TokenClaims, *, limit: int, offset: int) -> tuple[list[Persona], int]:
    base = select(Persona).where(or_(Persona.owner_user_id.is_(None), Persona.owner_user_id == user.user_id))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    # System presets first, then the caller's own by name: the presets are what a new
    # user picks from, so burying them under a long personal list helps nobody.
    rows = db.scalars(base.order_by(Persona.owner_user_id.isnot(None), Persona.name).limit(limit).offset(offset))
    return list(rows), total

def get_persona(db: Session, user: TokenClaims, persona_id: int) -> Persona:
    return _readable(db, user, persona_id)

def create_persona(db: Session, user: TokenClaims, payload) -> Persona:
    persona = Persona(
        owner_user_id=user.user_id,
        name=payload.name,
        length=payload.length,
        audience=payload.audience,
        technical_depth=payload.technical_depth,
        formality=payload.formality,
        instructions=payload.instructions,
        is_default=False,
    )
    db.add(persona)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a persona called {payload.name}")
    db.refresh(persona)
    if payload.is_default:
        return set_default(db, user, persona.id)
    return persona

def update_persona(db: Session, user: TokenClaims, persona_id: int, payload) -> Persona:
    persona = _writable(db, user, persona_id)
    fields = payload.model_dump(exclude_unset=True)
    # is_default is not a plain column write: it has to clear the previous default too.
    make_default = fields.pop("is_default", None)
    for field, value in fields.items():
        setattr(persona, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a persona with that name")
    db.refresh(persona)
    if make_default:
        return set_default(db, user, persona.id)
    return persona

def delete_persona(db: Session, user: TokenClaims, persona_id: int) -> None:
    persona = _writable(db, user, persona_id)
    db.delete(persona)
    db.commit()

def set_default(db: Session, user: TokenClaims, persona_id: int) -> Persona:
    """One default per user. The clear and the set are one transaction, or a crash
    between them leaves the user with two defaults or none."""
    persona = _writable(db, user, persona_id)
    db.execute(
        update(Persona)
        .where(Persona.owner_user_id == user.user_id, Persona.id != persona.id, Persona.is_default.is_(True))
        .values(is_default=False)
    )
    persona.is_default = True
    db.commit()
    db.refresh(persona)
    return persona

def system_default(db: Session) -> Persona:
    """The last resort. Materialised if the row is missing so a database that never ran
    0011's seed still generates text rather than 500ing on a tone setting."""
    persona = db.scalar(select(Persona).where(Persona.owner_user_id.is_(None), Persona.name == DEFAULT_SYSTEM_PERSONA))
    if persona is not None:
        return persona
    preset = next(p for p in PERSONA_SYSTEM_PRESETS if p["name"] == DEFAULT_SYSTEM_PERSONA)
    persona = Persona(owner_user_id=None, is_default=False, **preset)
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona

def resolve(db: Session, user: TokenClaims, persona_id: int | None = None) -> Persona:
    """Per-report override, then the user's default, then the system default."""
    if persona_id is not None:
        return _readable(db, user, persona_id)
    own_default = db.scalar(select(Persona).where(Persona.owner_user_id == user.user_id, Persona.is_default.is_(True)))
    if own_default is not None:
        return own_default
    return system_default(db)
