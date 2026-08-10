import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from crescent_core.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, PageParams, page_params


class _Item(BaseModel):
    id: int


def _app() -> TestClient:
    app = FastAPI()

    @app.get("/things", response_model=Page[_Item])
    def things(page: PageParams = Depends(page_params)):
        everything = [_Item(id=i) for i in range(500)]
        window = everything[page.offset : page.offset + page.limit]
        return Page.of(window, total=len(everything), params=page)

    return TestClient(app)


def test_defaults_apply_when_no_params_given():
    body = _app().get("/things").json()
    assert body["limit"] == DEFAULT_LIMIT
    assert body["offset"] == 0
    assert body["total"] == 500
    assert len(body["items"]) == DEFAULT_LIMIT


def test_offset_and_limit_window_the_results():
    body = _app().get("/things?limit=10&offset=20").json()
    assert body["limit"] == 10 and body["offset"] == 20
    assert [i["id"] for i in body["items"]] == list(range(20, 30))
    assert body["total"] == 500


def test_limit_is_capped():
    r = _app().get(f"/things?limit={MAX_LIMIT + 1}")
    assert r.status_code == 422


def test_limit_must_be_positive():
    assert _app().get("/things?limit=0").status_code == 422


def test_offset_cannot_be_negative():
    assert _app().get("/things?offset=-1").status_code == 422


def test_page_of_is_a_plain_constructor():
    page = Page.of([_Item(id=1)], total=1, params=PageParams(limit=50, offset=0))
    assert page.items[0].id == 1
    assert page.total == 1 and page.limit == 50 and page.offset == 0
