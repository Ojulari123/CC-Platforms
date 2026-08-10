from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar
from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int

def page_params(limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT), offset: int = Query(default=0, ge=0)) -> PageParams:
    return PageParams(limit=limit, offset=offset)

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, items: Sequence[T], *, total: int, params: PageParams) -> "Page[T]":
        return cls(items=list(items), total=total, limit=params.limit, offset=params.offset)
