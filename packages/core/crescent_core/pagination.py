"""
Shared pagination primitive for list endpoints lives here (not in any one service) so Pulse, Forge and identity all page and
filter lists the same way — same query params, same response shape — instead of
each inventing its own. The reporting lists in Pulse (reports, comments) are the
first place this really bites, but it's used the moment any list can grow.
"""
from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar
from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

@dataclass(frozen=True)
class PageParams:
    """limit/offset pulled from the query string, bounded so a caller can't ask
    for an unbounded page. Use as a FastAPI dependency via `page_params`."""
    limit: int
    offset: int

def page_params(limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT), offset: int = Query(default=0, ge=0)) -> PageParams:
    return PageParams(limit=limit, offset=offset)

class Page(BaseModel, Generic[T]):
    """A single page of results plus the total count, so a client can render
    'showing 1–50 of 214' and decide whether to ask for more."""
    items: list[T]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, items: Sequence[T], *, total: int, params: PageParams) -> "Page[T]":
        return cls(items=list(items), total=total, limit=params.limit, offset=params.offset)
