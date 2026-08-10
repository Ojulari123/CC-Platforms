# People are referenced by identity `user_id` only; Forge never reads identity's database.
from sqlalchemy import Boolean, Column, Index, Integer, String, Text, TIMESTAMP, func, text
from app.db import Base

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, index=True, nullable=True)
    is_sample = Column(Boolean, nullable=False, server_default="false", default=False)
    name = Column(String(200), nullable=False)
    original_filename = Column(String(400), nullable=True)
    content = Column(Text, nullable=False)  # the raw CSV text
    columns = Column(Text, nullable=False)
    row_count = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "uq_sample_name",
            "name",
            unique=True,
            sqlite_where=text("is_sample = 1"),
            postgresql_where=text("is_sample"),
        ),
    )
