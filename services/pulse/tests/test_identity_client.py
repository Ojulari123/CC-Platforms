"""The Pulse->identity service client: mint a client-credentials token, resolve
user_ids to emails and to profiles, cache the token and the profiles, and
refetch-once on a 401.

No network: httpx.post is monkeypatched to a handler that dispatches on URL and
returns real httpx.Response objects (so .json()/.status_code behave for real).
"""
import httpx
import pytest
from app.config import settings
from app.services import identity_client
from app.services.identity_client import IdentityResolutionError, resolve_emails, resolve_profiles, resolve_profiles_answer, resolve_profiles_safe

TOKEN_URL = "http://identity:8000/oauth/token"
EMAILS_URL = "http://identity:8000/internal/users/emails"
PROFILES_URL = "http://identity:8000/internal/users/profiles"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    # A configured secret + a clean token cache before every test, since the cache
    # is module-level and would otherwise leak between tests.
    monkeypatch.setattr(settings, "IDENTITY_API_URL", "http://identity:8000")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_ID", "pulse")
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "shh")
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    identity_client.clear_profile_cache()
    yield
    identity_client._cached_token = None
    identity_client._cached_expiry = 0.0
    identity_client.clear_profile_cache()


def _install(monkeypatch, handler):
    """Route identity_client's httpx.post through a URL-dispatching handler."""
    def _post(url, **kwargs):
        return handler(url, kwargs)
    monkeypatch.setattr(identity_client.httpx, "post", _post)


def test_token_fetch_then_email_lookup_happy_path(monkeypatch):
    calls = {"token": 0, "emails": 0}
    email_payloads = []

    def handler(url, kwargs):
        if url == TOKEN_URL:
            calls["token"] += 1
            assert kwargs["json"]["grant_type"] == "client_credentials"
            assert kwargs["json"]["client_secret"] == "shh"
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        assert url == EMAILS_URL
        calls["emails"] += 1
        assert kwargs["headers"]["Authorization"] == "Bearer svc-tok"
        email_payloads.append(kwargs["json"])
        return httpx.Response(200, json={"users": [
            {"user_id": 20, "email": "lead@x.com"},
            {"user_id": 25, "email": "deputy@x.com"},
        ]})

    _install(monkeypatch, handler)
    out = resolve_emails([20, 25])
    assert out == {20: "lead@x.com", 25: "deputy@x.com"}
    assert calls == {"token": 1, "emails": 1}
    assert email_payloads[0] == {"user_ids": [20, 25]}

    # A second call reuses the cached token — no new /oauth/token round-trip.
    resolve_emails([20])
    assert calls["token"] == 1
    assert calls["emails"] == 2


def test_401_triggers_one_refetch_and_retry(monkeypatch):
    calls = {"token": 0, "emails": 0}

    def handler(url, kwargs):
        if url == TOKEN_URL:
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{calls['token']}", "expires_in": 600})
        calls["emails"] += 1
        # First lookup is with the stale cached token -> 401; after a forced refetch the
        # retry succeeds.
        if calls["emails"] == 1:
            return httpx.Response(401, json={"detail": "expired"})
        assert kwargs["headers"]["Authorization"] == "Bearer tok-2"
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})

    _install(monkeypatch, handler)
    out = resolve_emails([20])
    assert out == {20: "lead@x.com"}
    assert calls["token"] == 2   # initial mint + one forced refetch
    assert calls["emails"] == 2  # first 401, then the retry


def test_empty_ids_short_circuits_without_calling(monkeypatch):
    def handler(url, kwargs):
        raise AssertionError("should not call identity for an empty id list")
    _install(monkeypatch, handler)
    assert resolve_emails([]) == {}


def test_missing_secret_raises_without_calling(monkeypatch):
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
    def handler(url, kwargs):
        raise AssertionError("should not call identity when unconfigured")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_token_endpoint_rejection_raises(monkeypatch):
    def handler(url, kwargs):
        return httpx.Response(401, json={"detail": "bad client"})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_token_response_without_access_token_raises(monkeypatch):
    def handler(url, kwargs):
        return httpx.Response(200, json={"expires_in": 600})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_transport_error_on_token_raises(monkeypatch):
    def handler(url, kwargs):
        raise httpx.ConnectError("identity unreachable")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_transport_error_on_lookup_raises(monkeypatch):
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        raise httpx.ConnectError("identity unreachable mid-lookup")
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_lookup_500_raises(monkeypatch):
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        return httpx.Response(500, json={"detail": "boom"})
    _install(monkeypatch, handler)
    with pytest.raises(IdentityResolutionError):
        resolve_emails([20])


def test_missing_expires_in_falls_back_and_still_works(monkeypatch):
    # No expires_in -> short fallback life; the call still succeeds this time.
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok"})
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})
    _install(monkeypatch, handler)
    assert resolve_emails([20]) == {20: "lead@x.com"}


def _profile(uid, first, last, avatar=None, active=True):
    return {"user_id": uid, "first_name": first, "last_name": last, "avatar_url": avatar, "is_active": active}


def _token_only(handler):
    """Wrap a profiles handler so /oauth/token always mints successfully."""
    def _h(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        return handler(url, kwargs)
    return _h


class TestResolveProfiles:
    def test_happy_path_and_unknown_ids_are_absent(self, monkeypatch):
        def handler(url, kwargs):
            assert url == PROFILES_URL
            assert kwargs["headers"]["Authorization"] == "Bearer svc-tok"
            assert kwargs["json"] == {"user_ids": [10, 20, 424242]}
            return httpx.Response(200, json={"users": [
                _profile(10, "Ada", "Lovelace", avatar="https://x/a.png"),
                _profile(20, "Grace", "Hopper", active=False),
            ]})

        _install(monkeypatch, _token_only(handler))
        out = resolve_profiles([10, 20, 424242])
        assert out[10] == _profile(10, "Ada", "Lovelace", avatar="https://x/a.png")
        assert out[20]["is_active"] is False
        assert 424242 not in out  # identity omits unknown ids; we don't invent a placeholder

    def test_keys_by_user_id_not_response_position(self, monkeypatch):
        # Identity returns rows in DATABASE order, not request order. Zipping by index
        # would silently hand Ada's name to Grace.
        def handler(url, kwargs):
            assert kwargs["json"] == {"user_ids": [10, 20, 30]}
            return httpx.Response(200, json={"users": [
                _profile(30, "Katherine", "Johnson"),
                _profile(20, "Grace", "Hopper"),
                _profile(10, "Ada", "Lovelace"),
            ]})

        _install(monkeypatch, _token_only(handler))
        out = resolve_profiles([10, 20, 30])
        assert out[10]["first_name"] == "Ada"
        assert out[20]["first_name"] == "Grace"
        assert out[30]["first_name"] == "Katherine"

    def test_batches_over_200_are_chunked(self, monkeypatch):
        sent = []

        def handler(url, kwargs):
            ids = kwargs["json"]["user_ids"]
            sent.append(ids)
            return httpx.Response(200, json={"users": [_profile(i, f"F{i}", f"L{i}") for i in ids]})

        _install(monkeypatch, _token_only(handler))
        out = resolve_profiles(list(range(1, 451)))
        assert [len(c) for c in sent] == [200, 200, 50]  # identity 422s past 200
        assert len(out) == 450
        assert out[450]["first_name"] == "F450"

    def test_cache_hit_avoids_a_second_lookup(self, monkeypatch):
        calls = {"profiles": 0}

        def handler(url, kwargs):
            calls["profiles"] += 1
            return httpx.Response(200, json={"users": [_profile(i, f"F{i}", f"L{i}") for i in kwargs["json"]["user_ids"]]})

        _install(monkeypatch, _token_only(handler))
        assert resolve_profiles([10, 20])[10]["first_name"] == "F10"
        assert calls["profiles"] == 1
        assert resolve_profiles([10, 20])[20]["first_name"] == "F20"
        assert calls["profiles"] == 1  # served entirely from cache

    def test_cache_only_fetches_the_missing_ids(self, monkeypatch):
        sent = []

        def handler(url, kwargs):
            sent.append(kwargs["json"]["user_ids"])
            return httpx.Response(200, json={"users": [_profile(i, f"F{i}", f"L{i}") for i in kwargs["json"]["user_ids"]]})

        _install(monkeypatch, _token_only(handler))
        resolve_profiles([10])
        out = resolve_profiles([10, 20])
        assert sent == [[10], [20]]
        assert set(out) == {10, 20}

    def test_expired_cache_entry_is_refetched(self, monkeypatch):
        monkeypatch.setattr(identity_client, "PROFILE_CACHE_TTL_SECONDS", -1)
        calls = {"profiles": 0}

        def handler(url, kwargs):
            calls["profiles"] += 1
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")]})

        _install(monkeypatch, _token_only(handler))
        resolve_profiles([10])
        resolve_profiles([10])
        assert calls["profiles"] == 2

    def test_empty_and_none_ids_short_circuit(self, monkeypatch):
        def handler(url, kwargs):
            raise AssertionError("should not call identity for an empty id list")
        _install(monkeypatch, handler)
        assert resolve_profiles([]) == {}
        assert resolve_profiles([None, None]) == {}

    def test_401_triggers_one_refetch_and_retry(self, monkeypatch):
        calls = {"token": 0, "profiles": 0}

        def handler(url, kwargs):
            if url == TOKEN_URL:
                calls["token"] += 1
                return httpx.Response(200, json={"access_token": f"tok-{calls['token']}", "expires_in": 600})
            calls["profiles"] += 1
            if calls["profiles"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            assert kwargs["headers"]["Authorization"] == "Bearer tok-2"
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")]})

        _install(monkeypatch, handler)
        assert resolve_profiles([10])[10]["first_name"] == "Ada"
        assert calls == {"token": 2, "profiles": 2}

    def test_403_raises(self, monkeypatch):
        # The rollout window: identity hasn't restarted with users:read:profile granted yet.
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(403, json={"detail": "scope"})))
        with pytest.raises(IdentityResolutionError):
            resolve_profiles([10])

    def test_transport_error_raises(self, monkeypatch):
        def handler(url, kwargs):
            raise httpx.ConnectError("identity unreachable")
        _install(monkeypatch, _token_only(handler))
        with pytest.raises(IdentityResolutionError):
            resolve_profiles([10])

    def test_missing_secret_raises_without_calling(self, monkeypatch):
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        def handler(url, kwargs):
            raise AssertionError("should not call identity when unconfigured")
        _install(monkeypatch, handler)
        with pytest.raises(IdentityResolutionError):
            resolve_profiles([10])

    def test_malformed_row_raises(self, monkeypatch):
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(200, json={"users": [{"user_id": 10}]})))
        with pytest.raises(KeyError):
            resolve_profiles([10])


class TestResolveProfilesSafe:
    def test_403_degrades_to_no_names(self, monkeypatch):
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(403, json={"detail": "scope"})))
        assert resolve_profiles_safe([10]) == {}

    def test_identity_unreachable_degrades_to_no_names(self, monkeypatch):
        def handler(url, kwargs):
            raise httpx.ConnectError("identity unreachable")
        _install(monkeypatch, handler)
        assert resolve_profiles_safe([10]) == {}

    def test_unexpected_error_degrades_to_no_names(self, monkeypatch):
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(200, json={"users": [{"user_id": 10}]})))
        assert resolve_profiles_safe([10]) == {}

    def test_unknown_ids_do_not_leak_into_the_names_it_returns(self, monkeypatch):
        # The display-name path is untouched by unknown_user_ids: it still only ever
        # sees rows identity sent, so people.py can't render a deleted user.
        def handler(url, kwargs):
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")], "unknown_user_ids": [20]})

        _install(monkeypatch, _token_only(handler))
        assert resolve_profiles_safe([10, 20]) == {10: _profile(10, "Ada", "Lovelace")}

    def test_partial_chunk_failure_keeps_the_chunk_that_worked(self, monkeypatch):
        calls = {"n": 0}

        def handler(url, kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                ids = kwargs["json"]["user_ids"]
                return httpx.Response(200, json={"users": [_profile(i, f"F{i}", f"L{i}") for i in ids]})
            return httpx.Response(500, json={"detail": "boom"})

        _install(monkeypatch, _token_only(handler))
        assert resolve_profiles_safe(list(range(1, 251))) == {}
        # The first chunk was cached before the second blew up, so the retry only
        # needs the 50 that are still missing — one call, not two.
        calls["n"] = 0
        assert len(resolve_profiles_safe(list(range(1, 251)))) == 250
        assert calls["n"] == 1


class TestResolveProfilesAnswer:
    """The variant a cleanup pass can act on. Two ids can be missing from `profiles`
    for opposite reasons — identity has no such user, or identity never answered —
    and only the first may ever cost someone their stored credential."""

    def test_reports_what_identity_said_about_every_id(self, monkeypatch):
        def handler(url, kwargs):
            assert kwargs["json"] == {"user_ids": [10, 20, 30]}
            return httpx.Response(200, json={
                "users": [_profile(10, "Ada", "Lovelace"), _profile(20, "Grace", "Hopper", active=False)],
                "unknown_user_ids": [30],
            })

        _install(monkeypatch, _token_only(handler))
        answer = resolve_profiles_answer([10, 20, 30])
        assert set(answer.profiles) == {10, 20}
        assert answer.profiles[20]["is_active"] is False
        assert answer.unknown == {30}

    def test_a_failed_chunk_lands_in_neither_field(self, monkeypatch):
        """The one that matters. Chunk 1 answers (including an unknown id), chunk 2
        blows up. Chunk 2's ids must be absent from `unknown` as well as `profiles`,
        or every user in a chunk identity happened to fail on looks deleted."""
        calls = {"n": 0}

        def handler(url, kwargs):
            calls["n"] += 1
            ids = kwargs["json"]["user_ids"]
            if calls["n"] == 1:
                return httpx.Response(200, json={
                    "users": [_profile(i, f"F{i}", f"L{i}") for i in ids if i != 7],
                    "unknown_user_ids": [7],
                })
            return httpx.Response(500, json={"detail": "boom"})

        _install(monkeypatch, _token_only(handler))
        answer = resolve_profiles_answer(list(range(1, 251)))
        assert answer.unknown == {7}
        assert set(answer.profiles) == set(range(1, 201)) - {7}
        assert not answer.unknown & set(range(201, 251))

    def test_total_failure_is_an_empty_answer_not_a_verdict(self, monkeypatch):
        def handler(url, kwargs):
            raise httpx.ConnectError("identity unreachable")

        _install(monkeypatch, _token_only(handler))
        answer = resolve_profiles_answer([10, 20])
        assert answer.profiles == {}
        assert answer.unknown == set()

    def test_403_during_a_scope_rollout_is_an_empty_answer(self, monkeypatch):
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(403, json={"detail": "scope"})))
        assert resolve_profiles_answer([10]) == ({}, set())

    def test_a_malformed_row_voids_its_whole_chunk(self, monkeypatch):
        # A row missing the fields Pulse pins means the answer isn't trustworthy, so
        # its unknown_user_ids isn't either.
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(
            200, json={"users": [{"user_id": 10}], "unknown_user_ids": [20]})))
        assert resolve_profiles_answer([10, 20]) == ({}, set())

    def test_unconfigured_service_client_answers_about_nobody(self, monkeypatch):
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")

        def handler(url, kwargs):
            raise AssertionError("should not call identity when unconfigured")

        _install(monkeypatch, handler)
        assert resolve_profiles_answer([10]) == ({}, set())

    def test_unknown_is_never_cached(self, monkeypatch):
        """A 403 mid-rollout or a user created seconds ago must not be pinned as
        'does not exist' for the cache TTL — every pass re-asks about them."""
        sent = []

        def handler(url, kwargs):
            sent.append(kwargs["json"]["user_ids"])
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")], "unknown_user_ids": [20]})

        _install(monkeypatch, _token_only(handler))
        assert resolve_profiles_answer([10, 20]).unknown == {20}
        assert resolve_profiles_answer([10, 20]).unknown == {20}
        assert sent == [[10, 20], [20]]  # 10 served from cache, 20 asked about again

    def test_a_fully_cached_answer_claims_nothing_is_unknown(self, monkeypatch):
        def handler(url, kwargs):
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")], "unknown_user_ids": []})

        _install(monkeypatch, _token_only(handler))
        resolve_profiles_answer([10])

        def _no_calls(url, kwargs):
            raise AssertionError("everything wanted is cached; should not call identity")

        _install(monkeypatch, _no_calls)
        answer = resolve_profiles_answer([10])
        assert set(answer.profiles) == {10}
        assert answer.unknown == set()

    def test_empty_ids_short_circuit(self, monkeypatch):
        def handler(url, kwargs):
            raise AssertionError("should not call identity for an empty id list")

        _install(monkeypatch, handler)
        assert resolve_profiles_answer([]) == ({}, set())
        assert resolve_profiles_answer([None]) == ({}, set())

    def test_an_identity_without_the_field_reports_nothing_unknown(self, monkeypatch):
        # Backward compatibility: an older identity omits unknown_user_ids entirely,
        # which has to read as "said nothing", never as "none are deleted... or all".
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(
            200, json={"users": [_profile(10, "Ada", "Lovelace")]})))
        answer = resolve_profiles_answer([10, 20])
        assert set(answer.profiles) == {10}
        assert answer.unknown == set()
