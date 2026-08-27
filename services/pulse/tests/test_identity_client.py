import logging
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
        if calls["emails"] == 1:
            return httpx.Response(401, json={"detail": "expired"})
        assert kwargs["headers"]["Authorization"] == "Bearer tok-2"
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})

    _install(monkeypatch, handler)
    out = resolve_emails([20])
    assert out == {20: "lead@x.com"}
    assert calls["token"] == 2
    assert calls["emails"] == 2


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


def test_missing_secret_message_does_not_name_the_variable(monkeypatch, caplog):
    """Every caller swallows this today; the message has to stay safe for the one that won't."""
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
    _install(monkeypatch, lambda url, kwargs: pytest.fail("should not call identity when unconfigured"))
    with caplog.at_level(logging.ERROR, logger="app.services.identity_client"):
        with pytest.raises(IdentityResolutionError) as exc:
            resolve_emails([20])
    message = str(exc.value)
    assert "PULSE_SERVICE_CLIENT_SECRET" not in message and ".env" not in message
    assert message == "Identity lookups are not configured on this server; cannot resolve emails"
    assert "PULSE_SERVICE_CLIENT_SECRET" in caplog.text


def test_transport_error_messages_do_not_carry_the_identity_url(monkeypatch, caplog):
    def handler(url, kwargs):
        raise httpx.ConnectError(f"connection to {url} refused")

    _install(monkeypatch, handler)
    with caplog.at_level(logging.ERROR, logger="app.services.identity_client"):
        with pytest.raises(IdentityResolutionError) as exc:
            resolve_emails([20])
    assert "http://identity:8000" not in str(exc.value)
    assert "http://identity:8000" in caplog.text


def test_lookup_transport_error_message_does_not_carry_the_identity_url(monkeypatch, caplog):
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok", "expires_in": 600})
        raise httpx.ConnectError(f"connection to {url} refused")

    _install(monkeypatch, handler)
    with caplog.at_level(logging.ERROR, logger="app.services.identity_client"):
        with pytest.raises(IdentityResolutionError) as exc:
            resolve_emails([20])
    assert "http://identity:8000" not in str(exc.value)
    assert str(exc.value) == "Could not reach the identity service to resolve email"
    assert "http://identity:8000" in caplog.text


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
    def handler(url, kwargs):
        if url == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "svc-tok"})
        return httpx.Response(200, json={"users": [{"user_id": 20, "email": "lead@x.com"}]})
    _install(monkeypatch, handler)
    assert resolve_emails([20]) == {20: "lead@x.com"}


def _profile(uid, first, last, avatar=None, active=True):
    return {"user_id": uid, "first_name": first, "last_name": last, "avatar_url": avatar, "is_active": active}


def _token_only(handler):
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
        assert 424242 not in out

    def test_keys_by_user_id_not_response_position(self, monkeypatch):
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
        assert [len(c) for c in sent] == [200, 200, 50]
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
        assert calls["profiles"] == 1

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

    def test_missing_secret_message_does_not_name_the_variable(self, monkeypatch, caplog):
        monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
        _install(monkeypatch, lambda url, kwargs: pytest.fail("should not call identity when unconfigured"))
        with caplog.at_level(logging.ERROR, logger="app.services.identity_client"):
            with pytest.raises(IdentityResolutionError) as exc:
                resolve_profiles([10])
        message = str(exc.value)
        assert "PULSE_SERVICE_CLIENT_SECRET" not in message and ".env" not in message
        assert message == "Identity lookups are not configured on this server; cannot resolve profiles"
        assert "PULSE_SERVICE_CLIENT_SECRET" in caplog.text

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
        calls["n"] = 0
        assert len(resolve_profiles_safe(list(range(1, 251)))) == 250
        assert calls["n"] == 1


class TestResolveProfilesAnswer:

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
        sent = []

        def handler(url, kwargs):
            sent.append(kwargs["json"]["user_ids"])
            return httpx.Response(200, json={"users": [_profile(10, "Ada", "Lovelace")], "unknown_user_ids": [20]})

        _install(monkeypatch, _token_only(handler))
        assert resolve_profiles_answer([10, 20]).unknown == {20}
        assert resolve_profiles_answer([10, 20]).unknown == {20}
        assert sent == [[10, 20], [20]]

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
        _install(monkeypatch, _token_only(lambda url, kwargs: httpx.Response(
            200, json={"users": [_profile(10, "Ada", "Lovelace")]})))
        answer = resolve_profiles_answer([10, 20])
        assert set(answer.profiles) == {10}
        assert answer.unknown == set()


DEPT_ADMINS_URL = "http://identity:8000/internal/departments/7/admins"
PLATFORM_ADMINS_URL = "http://identity:8000/internal/platform-admins"


def _install_get(monkeypatch, handler):
    def _get(url, **kwargs):
        return handler(url, kwargs)
    monkeypatch.setattr(identity_client.httpx, "get", _get)


def _install_token_post(monkeypatch, token="svc-tok"):
    def _post(url, **kwargs):
        assert url == TOKEN_URL
        return httpx.Response(200, json={"access_token": token, "expires_in": 600})
    monkeypatch.setattr(identity_client.httpx, "post", _post)


def test_dept_admin_lookup_sends_the_service_token_and_maps_the_answer(monkeypatch):
    seen = []
    _install_token_post(monkeypatch)

    def handler(url, kwargs):
        seen.append((url, kwargs["headers"]["Authorization"]))
        return httpx.Response(200, json={"users": [
            {"user_id": 41, "email": "admin@x.com"},
            {"user_id": 42, "email": "other@x.com"},
        ]})

    _install_get(monkeypatch, handler)
    assert identity_client.resolve_dept_admin_emails(7) == {41: "admin@x.com", 42: "other@x.com"}
    assert seen == [(DEPT_ADMINS_URL, "Bearer svc-tok")]


def test_platform_admin_lookup_maps_the_answer(monkeypatch):
    _install_token_post(monkeypatch)
    _install_get(monkeypatch, lambda url, kwargs: httpx.Response(200, json={"users": [{"user_id": 99, "email": "root@x.com"}]})
                 if url == PLATFORM_ADMINS_URL else pytest.fail(url))
    assert identity_client.resolve_platform_admin_emails() == {99: "root@x.com"}


def test_a_department_with_no_admins_is_an_empty_dict_not_an_error(monkeypatch):
    _install_token_post(monkeypatch)
    _install_get(monkeypatch, lambda url, kwargs: httpx.Response(200, json={"users": []}))
    assert identity_client.resolve_dept_admin_emails(7) == {}


def test_the_dept_id_is_coerced_so_it_cannot_reshape_the_path(monkeypatch):
    """The dept_id is interpolated into a URL path, so it goes through int() first."""
    _install_token_post(monkeypatch)
    _install_get(monkeypatch, lambda url, kwargs: httpx.Response(200, json={"users": []}))
    with pytest.raises(ValueError):
        identity_client.resolve_dept_admin_emails("7/../platform-admins")


def test_a_401_on_an_admin_lookup_re_mints_the_token_once(monkeypatch):
    tokens = iter(["stale", "fresh"])
    minted = []

    def _post(url, **kwargs):
        assert url == TOKEN_URL
        tok = next(tokens)
        minted.append(tok)
        return httpx.Response(200, json={"access_token": tok, "expires_in": 600})

    monkeypatch.setattr(identity_client.httpx, "post", _post)

    def handler(url, kwargs):
        if kwargs["headers"]["Authorization"] == "Bearer stale":
            return httpx.Response(401)
        return httpx.Response(200, json={"users": [{"user_id": 99, "email": "root@x.com"}]})

    _install_get(monkeypatch, handler)
    assert identity_client.resolve_platform_admin_emails() == {99: "root@x.com"}
    assert minted == ["stale", "fresh"]


def test_a_403_on_an_admin_lookup_raises_rather_than_reading_as_nobody(monkeypatch):
    """A missing admins:read scope must not look like a department with no admins."""
    _install_token_post(monkeypatch)
    _install_get(monkeypatch, lambda url, kwargs: httpx.Response(403))
    with pytest.raises(IdentityResolutionError):
        identity_client.resolve_dept_admin_emails(7)


def test_a_transport_failure_on_an_admin_lookup_raises(monkeypatch, caplog):
    _install_token_post(monkeypatch)

    def handler(url, kwargs):
        raise httpx.ConnectError("no route to host")

    _install_get(monkeypatch, handler)
    with caplog.at_level(logging.ERROR, logger="app.services.identity_client"):
        with pytest.raises(IdentityResolutionError):
            identity_client.resolve_platform_admin_emails()
    # The internal identity URL stays in the log, never in the raised message.
    assert "no route to host" in caplog.text


def test_admin_lookups_refuse_without_service_credentials(monkeypatch):
    monkeypatch.setattr(settings, "PULSE_SERVICE_CLIENT_SECRET", "")
    with pytest.raises(IdentityResolutionError):
        identity_client.resolve_dept_admin_emails(7)
    with pytest.raises(IdentityResolutionError):
        identity_client.resolve_platform_admin_emails()
