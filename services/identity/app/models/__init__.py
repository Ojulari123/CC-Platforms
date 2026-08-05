from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.db import Base

class User(Base):
    """Identity fields only — name, email, password, avatar. No product-specific data lives here.
    Products keep their own view of a user keyed by user_id."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    email_verified = Column(Boolean, nullable=False, server_default="false", default=False)
    is_platform_admin = Column(Boolean, nullable=False, server_default="false", default=False)
    token_version = Column(Integer, nullable=False, server_default="0", default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    head_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    teams = relationship("Team", back_populates="department", cascade="all, delete-orphan")
    memberships = relationship("Membership", back_populates="department", cascade="all, delete-orphan")

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), nullable=False)
    manager_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    department = relationship("Department", back_populates="teams")
    memberships = relationship("Membership", back_populates="team")

    __table_args__ = (UniqueConstraint("dept_id", "slug", name="uq_team_dept_slug"),)

class Membership(Base):
    """A user belongs to a department (and optionally a team within it) with a role.
    Multi-department-ready: schema allows multiple active memberships per user. For now we
    only ever issue one until the supervisor confirms multi-department."""
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dept_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    role = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="memberships")
    department = relationship("Department", back_populates="memberships")
    team = relationship("Team", back_populates="memberships")

    __table_args__ = (UniqueConstraint("user_id", "dept_id", name="uq_membership_user_dept"),)

class RefreshToken(Base):
    """Opaque refresh token stored as SHA-256 hash — never the raw value.
    family_id groups every token descended from the same login.
    
    Reusing a revoked token nukes the whole family (stolen-token detection)."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = Column(String(64), index=True, nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, server_default="false", default=False)
    replaced_by = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="refresh_tokens")

class Invite(Base):
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    department = relationship("Department")

class PasswordResetToken(Base):
    """One-time forgot-password token. Same hashing pattern as RefreshToken and
    Invite (only the SHA-256 hash is stored); the raw value lives solely in the
    emailed link. Short-lived and single-use; requesting a new one invalidates
    any earlier unused token for the same user."""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
