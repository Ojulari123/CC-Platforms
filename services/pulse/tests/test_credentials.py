import pytest
from app.config import settings
from app.models import LLM_KIND_CHAT, PROVIDER_ANTHROPIC, PROVIDER_OPENAI, SCOPE_DEPARTMENT, SCOPE_USER, ApiCredential, LlmUsage
from app.services import credentials as credentials_service, llm_budget
from app.services.credentials import InvalidApiKeyError, ResolvedCredential
from app.services.llm_budget import BudgetExceededError

DEPT = 1
OTHER_DEPT = 2

MEMBER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
OTHER_MEMBER = dict(user_id=11, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": DEPT, "team_id": None, "role": "admin"}])
OTHER_DEPT_ADMIN = dict(user_id=31, memberships=[{"dept_id": OTHER_DEPT, "team_id": None, "role": "admin"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)

USER_KEY = "sk-user-key-abcd"
DEPT_KEY = "sk-dept-key-wxyz"
PLATFORM_KEY = "sk-platform-key-0000"

# Captured before the autouse fixture below replaces it, so TestProbeSeam can exercise
# the real thing.
REAL_PROBE = credentials_service.probe_key

@pytest.fixture(autouse=True)
def accept_every_key(monkeypatch):
    """The one place credentials.py touches the network. Every test that stores a key
    goes through this seam."""
    monkeypatch.setattr(credentials_service, "probe_key", lambda provider, key: None)

@pytest.fixture
def no_platform_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

@pytest.fixture
def platform_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", PLATFORM_KEY)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

def _put(client, **body):
    body.setdefault("scope", SCOPE_USER)
    body.setdefault("provider", PROVIDER_OPENAI)
    body.setdefault("key", USER_KEY)
    return client.put("/settings/credentials", json=body)

class TestUserScope:
    def test_storing_a_key_reports_only_its_last_four(self, client, act_as):
        act_as(**MEMBER)
        r = _put(client)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["last_four"] == "abcd"
        assert body["scope"] == SCOPE_USER
        assert body["owner_user_id"] == 10
        assert body["created_by_user_id"] == 10

    def test_the_key_is_encrypted_at_rest(self, client, act_as, db):
        act_as(**MEMBER)
        _put(client)

        row = db.query(ApiCredential).one()
        assert row.key_encrypted != USER_KEY
        assert USER_KEY not in row.key_encrypted
        assert credentials_service.crypto.decrypt(row.key_encrypted) == USER_KEY

    def test_a_second_put_replaces_rather_than_duplicates(self, client, act_as, db):
        act_as(**MEMBER)
        first = _put(client).json()["id"]
        second = _put(client, key="sk-user-key-9999", model="gpt-4o").json()

        assert second["id"] == first
        assert second["last_four"] == "9999"
        assert second["model"] == "gpt-4o"
        assert db.query(ApiCredential).count() == 1

    def test_a_plain_member_cannot_set_someone_elses_user_key(self, client, act_as):
        act_as(**MEMBER)
        assert _put(client, owner_user_id=11).status_code == 403

    def test_a_platform_admin_can_set_someone_elses_user_key(self, client, act_as):
        act_as(**PLATFORM)
        r = _put(client, owner_user_id=11)
        assert r.status_code == 200, r.text
        assert r.json()["owner_user_id"] == 11

    def test_an_invalid_key_is_refused_and_nothing_is_stored(self, client, act_as, db, monkeypatch):
        def _reject(provider, key):
            raise InvalidApiKeyError("openai rejected this key. Check it and try again.")

        monkeypatch.setattr(credentials_service, "probe_key", _reject)
        act_as(**MEMBER)

        r = _put(client)
        assert r.status_code == 422
        assert "rejected this key" in r.json()["detail"]
        assert db.query(ApiCredential).count() == 0

    def test_a_blank_key_never_reaches_the_provider(self, client, act_as):
        act_as(**MEMBER)
        assert _put(client, key="   ").status_code == 422

class TestEditingWithoutResupplyingTheKey:
    """The cap flag and the model are settings, not secrets. Making a caller paste the
    key again just to flip a toggle is how stale keys get pasted in."""

    def test_the_cap_flag_can_be_flipped_with_no_key(self, client, act_as, db):
        act_as(**MEMBER)
        created = _put(client).json()
        assert created["bypass_token_cap"] is False

        r = client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "bypass_token_cap": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["id"] == created["id"]
        assert r.json()["bypass_token_cap"] is True
        assert db.query(ApiCredential).count() == 1

    def test_the_stored_key_survives_an_update_that_omits_it(self, client, act_as, db):
        act_as(**MEMBER)
        _put(client)
        client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "bypass_token_cap": True,
        })

        row = db.query(ApiCredential).one()
        assert credentials_service.crypto.decrypt(row.key_encrypted) == USER_KEY
        assert row.last_four == "abcd"

    def test_the_model_can_be_changed_with_no_key(self, client, act_as):
        act_as(**MEMBER)
        _put(client, model="gpt-4o")
        r = client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "model": "gpt-4o-mini",
        })
        assert r.status_code == 200, r.text
        assert r.json()["model"] == "gpt-4o-mini"
        assert r.json()["last_four"] == "abcd"

    def test_an_omitted_key_is_never_probed(self, client, act_as, monkeypatch):
        act_as(**MEMBER)
        _put(client)

        def _explode(provider, key):
            raise AssertionError("probe_key was called for an update that supplied no key")

        monkeypatch.setattr(credentials_service, "probe_key", _explode)
        r = client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "bypass_token_cap": True,
        })
        assert r.status_code == 200, r.text

    def test_creating_without_a_key_is_refused(self, client, act_as, db):
        act_as(**MEMBER)
        r = client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "bypass_token_cap": True,
        })
        assert r.status_code == 422
        assert "required the first time" in r.json()["detail"]
        assert db.query(ApiCredential).count() == 0

    def test_a_key_that_is_supplied_on_update_is_still_probed_and_can_still_be_refused(self, client, act_as, db, monkeypatch):
        act_as(**MEMBER)
        _put(client)

        def _reject(provider, key):
            raise InvalidApiKeyError("openai rejected this key. Check it and try again.")

        monkeypatch.setattr(credentials_service, "probe_key", _reject)
        r = _put(client, key="sk-user-key-dead", bypass_token_cap=True)
        assert r.status_code == 422
        assert "rejected this key" in r.json()["detail"]

        row = db.query(ApiCredential).one()
        assert row.last_four == "abcd"
        assert row.bypass_token_cap is False

    def test_a_blank_key_is_still_refused_rather_than_read_as_omitted(self, client, act_as):
        act_as(**MEMBER)
        _put(client)
        assert _put(client, key="   ").status_code == 422

    def test_a_department_key_can_be_edited_without_the_key_too(self, client, act_as, db):
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        r = client.put("/settings/credentials", json={
            "scope": SCOPE_DEPARTMENT, "provider": PROVIDER_OPENAI, "dept_id": DEPT,
            "bypass_token_cap": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["bypass_token_cap"] is True
        assert db.query(ApiCredential).one().last_four == "wxyz"

    def test_permissions_still_apply_when_no_key_is_supplied(self, client, act_as):
        act_as(**MEMBER)
        r = client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI,
            "owner_user_id": 11, "bypass_token_cap": True,
        })
        assert r.status_code == 403

    def test_a_lifted_cap_set_without_the_key_really_takes_effect(self, client, act_as, db, monkeypatch, no_platform_key):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _put(client)
        client.put("/settings/credentials", json={
            "scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "bypass_token_cap": True,
        })
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.bypass_token_cap is True
        llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)

class TestDepartmentScope:
    def test_a_department_admin_may_set_a_department_key(self, client, act_as):
        act_as(**DEPT_ADMIN)
        r = _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        assert r.status_code == 200, r.text
        assert r.json()["dept_id"] == DEPT
        assert r.json()["owner_user_id"] is None

    def test_a_plain_member_may_not(self, client, act_as):
        act_as(**MEMBER)
        assert _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY).status_code == 403

    def test_an_admin_of_another_department_may_not(self, client, act_as):
        act_as(**OTHER_DEPT_ADMIN)
        assert _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY).status_code == 403

    def test_a_platform_admin_may(self, client, act_as):
        act_as(**PLATFORM)
        assert _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY).status_code == 200

    def test_a_department_key_without_a_department_is_refused(self, client, act_as):
        act_as(**DEPT_ADMIN)
        assert _put(client, scope=SCOPE_DEPARTMENT, key=DEPT_KEY).status_code == 422

class TestResolutionOrder:
    def test_the_users_own_key_wins(self, client, act_as, db, platform_key):
        admin = act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        member = act_as(**MEMBER)
        _put(client, key=USER_KEY)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.source == "user"
        assert resolved.key == USER_KEY
        assert credentials_service.resolve_credential(db, admin).key == DEPT_KEY

    def test_the_department_key_is_next(self, client, act_as, db, platform_key):
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        member = act_as(**MEMBER)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.source == "department"
        assert resolved.key == DEPT_KEY

    def test_a_department_key_does_not_reach_another_department(self, client, act_as, db, platform_key):
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        outsider = act_as(**OTHER_DEPT_ADMIN)

        assert credentials_service.resolve_credential(db, outsider).source == "platform"

    def test_the_platform_env_key_is_the_fallback(self, act_as, db, platform_key):
        member = act_as(**MEMBER)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.source == "platform"
        assert resolved.key == PLATFORM_KEY
        assert resolved.provider == PROVIDER_OPENAI
        assert resolved.credential_id is None

    def test_nothing_configured_resolves_to_nothing(self, act_as, db, no_platform_key):
        member = act_as(**MEMBER)

        assert credentials_service.resolve_credential(db, member) is None

    def test_deleting_a_key_falls_back_to_the_next_one(self, client, act_as, db, platform_key):
        member = act_as(**MEMBER)
        cid = _put(client).json()["id"]
        assert credentials_service.resolve_credential(db, member).source == "user"

        assert client.delete(f"/settings/credentials/{cid}").status_code == 204
        assert credentials_service.resolve_credential(db, member).source == "platform"

    def test_a_pinned_ai_provider_is_pinned_here_too(self, client, act_as, db, monkeypatch, platform_key):
        monkeypatch.setattr(settings, "AI_PROVIDER", PROVIDER_ANTHROPIC)
        member = act_as(**MEMBER)
        _put(client, provider=PROVIDER_OPENAI, key=USER_KEY)

        # ANTHROPIC_API_KEY is blank and the only stored key is an OpenAI one, so a
        # deployment pinned to Anthropic has nothing to answer with.
        assert credentials_service.resolve_credential(db, member) is None

    def test_asking_for_one_provider_ignores_a_key_for_the_other(self, client, act_as, db, no_platform_key):
        member = act_as(**MEMBER)
        _put(client, provider=PROVIDER_ANTHROPIC, key="sk-ant-key-abcd")

        assert credentials_service.resolve_credential(db, member, provider=PROVIDER_ANTHROPIC).source == "user"
        assert credentials_service.resolve_credential(db, member, provider=PROVIDER_OPENAI) is None

class TestEffectiveEndpoint:
    def test_it_reports_the_users_own_key(self, client, act_as, platform_key):
        act_as(**MEMBER)
        _put(client, model="gpt-4o")

        body = client.get("/settings/credentials/effective").json()
        assert body == {"source": "user", "provider": PROVIDER_OPENAI, "model": "gpt-4o", "bypass_token_cap": False}

    def test_it_reports_the_department_key(self, client, act_as, platform_key):
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        act_as(**MEMBER)

        assert client.get("/settings/credentials/effective").json()["source"] == "department"

    def test_it_reports_the_platform_env_key(self, client, act_as, platform_key):
        act_as(**MEMBER)

        body = client.get("/settings/credentials/effective").json()
        assert body["source"] == "platform"
        assert body["model"] == settings.LLM_MODEL

    def test_it_reports_none_when_nothing_is_configured(self, client, act_as, no_platform_key):
        act_as(**MEMBER)

        assert client.get("/settings/credentials/effective").json() == {
            "source": "none", "provider": None, "model": None, "bypass_token_cap": False,
        }

class TestTheKeyIsNeverReturned:
    def test_not_by_put_get_or_effective(self, client, act_as, platform_key):
        act_as(**MEMBER)
        put = client.put("/settings/credentials", json={"scope": SCOPE_USER, "provider": PROVIDER_OPENAI, "key": USER_KEY})
        listed = client.get("/settings/credentials")
        effective = client.get("/settings/credentials/effective")

        for response in (put, listed, effective):
            assert USER_KEY not in response.text
            assert "key_encrypted" not in response.text
        assert "key" not in put.json()
        assert put.json()["last_four"] == "abcd"

    def test_the_platform_env_key_is_not_returned_either(self, client, act_as, platform_key):
        act_as(**MEMBER)

        assert PLATFORM_KEY not in client.get("/settings/credentials/effective").text

class TestListAndDelete:
    def test_a_member_sees_their_own_and_their_departments(self, client, act_as):
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        act_as(**MEMBER)
        _put(client)

        scopes = sorted(c["scope"] for c in client.get("/settings/credentials").json()["items"])
        assert scopes == [SCOPE_DEPARTMENT, SCOPE_USER]

    def test_another_users_key_is_not_listed(self, client, act_as):
        act_as(**MEMBER)
        _put(client)
        act_as(**OTHER_MEMBER)

        assert client.get("/settings/credentials").json()["items"] == []

    def test_another_users_key_cannot_be_deleted(self, client, act_as):
        act_as(**MEMBER)
        cid = _put(client).json()["id"]
        act_as(**OTHER_MEMBER)

        assert client.delete(f"/settings/credentials/{cid}").status_code == 404

    def test_a_plain_member_cannot_delete_the_department_key_they_can_see(self, client, act_as):
        act_as(**DEPT_ADMIN)
        cid = _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY).json()["id"]
        act_as(**MEMBER)

        assert client.delete(f"/settings/credentials/{cid}").status_code == 403

    def test_a_platform_admin_sees_everything(self, client, act_as):
        act_as(**MEMBER)
        _put(client)
        act_as(**PLATFORM)

        assert len(client.get("/settings/credentials").json()["items"]) == 1

    def test_deleting_something_that_is_not_there_is_404(self, client, act_as):
        act_as(**MEMBER)
        assert client.delete("/settings/credentials/404").status_code == 404

    def test_requires_a_token(self, client):
        assert client.get("/settings/credentials").status_code == 401

def _spend(db, user_id, tokens):
    db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=user_id, tokens=tokens))
    db.commit()

class TestCapBypass:
    """You may only lift a cap on spend you are paying for."""

    def test_a_user_key_may_bypass_the_cap(self, client, act_as, db, monkeypatch, no_platform_key):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _put(client, bypass_token_cap=True)
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.bypass_token_cap is True
        llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)

    def test_a_department_key_may_bypass_the_cap(self, client, act_as, db, monkeypatch, no_platform_key):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY, bypass_token_cap=True)
        member = act_as(**MEMBER)
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.source == "department"
        llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)

    def test_bypass_is_off_unless_it_was_asked_for(self, client, act_as, db, monkeypatch, no_platform_key):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _put(client)
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.bypass_token_cap is False
        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)

    def test_the_platform_env_key_can_never_bypass_the_cap(self, act_as, db, monkeypatch, platform_key):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        assert resolved.source == "platform"
        assert resolved.bypass_token_cap is False
        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)

    def test_a_forged_platform_credential_still_cannot_bypass(self, act_as, db, monkeypatch):
        """The guard is on the source, not on who built the object: nothing that says
        `platform` skips the cap, whatever else it claims."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _spend(db, member.user_id, 5000)
        forged = ResolvedCredential(
            source="platform", provider=PROVIDER_OPENAI, key=PLATFORM_KEY,
            model=None, bypass_token_cap=True,
        )

        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=forged)

    def test_no_credential_at_all_still_enforces_the_cap(self, act_as, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _spend(db, member.user_id, 5000)

        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT)

    def test_usage_is_still_metered_when_the_cap_is_lifted(self, client, act_as, db, monkeypatch, no_platform_key):
        """Uncapped is not unmetered — the spend has to stay visible."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1000)
        member = act_as(**MEMBER)
        _put(client, bypass_token_cap=True)
        _spend(db, member.user_id, 5000)

        resolved = credentials_service.resolve_credential(db, member)
        llm_budget.check_budget(db, member.user_id, kind=LLM_KIND_CHAT, credential=resolved)
        assert llm_budget.tokens_used_today(db, member.user_id) == 5000

class TestProviderWiring:
    def test_generate_spends_the_supplied_key_and_model(self, monkeypatch):
        from app.services import ai_provider

        seen = {}

        class _Response:
            choices = [type("C", (), {"message": type("M", (), {"content": "text from the caller's own key"})()})()]
            model = "gpt-4o"
            usage = type("U", (), {"total_tokens": 12})()

        def _build(credential=None):
            seen["api_key"] = credential.key if credential else settings.LLM_API_KEY
            return object()

        def _call(client, system, user, max_tokens, model=None):
            seen["model"] = model
            return _Response()

        monkeypatch.setattr(ai_provider, "_build_openai_client", _build)
        monkeypatch.setattr(ai_provider, "_call_openai_once", _call)
        credential = ResolvedCredential(source="user", provider=PROVIDER_OPENAI, key=USER_KEY, model="gpt-4o", bypass_token_cap=False)

        result = ai_provider.generate("sys", "usr", max_tokens=10, credential=credential)

        assert seen == {"api_key": USER_KEY, "model": "gpt-4o"}
        assert result.text == "text from the caller's own key"

    def test_generate_without_a_credential_still_uses_the_env_key(self, monkeypatch, platform_key):
        from app.services import ai_provider

        seen = {}

        class _Response:
            choices = [type("C", (), {"message": type("M", (), {"content": "env text"})()})()]
            model = settings.LLM_MODEL
            usage = None

        monkeypatch.setattr(ai_provider, "_build_openai_client", lambda credential=None: seen.setdefault("credential", credential))
        monkeypatch.setattr(ai_provider, "_call_openai_once", lambda *a, **k: _Response())

        assert ai_provider.generate("sys", "usr", max_tokens=10).text == "env text"
        assert seen["credential"] is None

    def test_embeddings_use_an_openai_credential(self, monkeypatch):
        from app.services import embeddings

        credential = ResolvedCredential(source="user", provider=PROVIDER_OPENAI, key=USER_KEY, model="gpt-4o", bypass_token_cap=False)

        assert embeddings._openai_key(credential) == USER_KEY

    def test_embeddings_fall_back_when_the_credential_is_anthropic(self, monkeypatch, platform_key):
        from app.services import embeddings

        credential = ResolvedCredential(source="user", provider=PROVIDER_ANTHROPIC, key="sk-ant", model=None, bypass_token_cap=False)

        assert embeddings._openai_key(credential) == PLATFORM_KEY
        assert embeddings._openai_key(None) == PLATFORM_KEY

class TestProbeSeam:
    def test_a_provider_error_becomes_invalidapikeyerror_without_the_key(self, monkeypatch):
        # The probe builds its client inside the function, so a bad key fails at the
        # first call rather than at import. No network: the client constructor raises.
        def _boom(*args, **kwargs):
            raise RuntimeError("bad request with sk-secret-do-not-log")

        monkeypatch.setattr("openai.OpenAI", _boom)

        with pytest.raises(InvalidApiKeyError) as exc:
            REAL_PROBE(PROVIDER_OPENAI, "sk-secret-do-not-log")
        assert "sk-secret-do-not-log" not in str(exc.value)
        assert "openai rejected this key" in str(exc.value)

    def test_the_anthropic_branch_is_separate(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("nope")

        monkeypatch.setattr("anthropic.Anthropic", _boom)

        with pytest.raises(InvalidApiKeyError) as exc:
            REAL_PROBE(PROVIDER_ANTHROPIC, "sk-ant-nope")
        assert "anthropic rejected this key" in str(exc.value)


def _budget(client, **body):
    body.setdefault("scope", SCOPE_USER)
    return client.put("/settings/credentials/budgets", json=body)


class TestBudgetResolution:
    """user, then department, then a platform row, then the environment variable. The
    same order a key resolves in, because the two answer halves of one question."""

    def test_with_nothing_stored_the_environment_variable_is_the_cap(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (200_000, "platform_default")

    def test_a_platform_row_overrides_the_environment_variable(self, client, act_as, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        act_as(**PLATFORM)
        assert _budget(client, scope="platform", daily_token_cap=50_000).status_code == 200

        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (50_000, "platform")

    def test_a_department_row_beats_the_platform_row(self, client, act_as, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        act_as(**DEPT_ADMIN)
        assert _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=20_000).status_code == 200

        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (20_000, "department")
        assert credentials_service.resolve_cap(db, 10, dept_ids=(OTHER_DEPT,)) == (200_000, "platform_default")

    def test_the_users_own_row_beats_everything(self, client, act_as, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        act_as(**DEPT_ADMIN)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=20_000)
        act_as(**MEMBER)
        assert _budget(client, daily_token_cap=5_000).status_code == 200

        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (5_000, "user")

    def test_a_worker_with_no_memberships_cannot_see_a_department_row(self, client, act_as, db, monkeypatch):
        """The same gap resolve_for_user_id has, and the same direction: a Celery task
        holds a user id and nothing else, so it falls back to the platform cap rather
        than to a department allowance it cannot prove the user belongs to."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        act_as(**DEPT_ADMIN)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=20_000)

        assert credentials_service.resolve_cap(db, 10) == (200_000, "platform_default")


class TestOnlyRelaxWhatYouPayFor:
    """Lowering an allowance is always allowed. Raising one is only allowed where the
    spend it unlocks is yours."""

    def test_a_user_on_the_platform_key_cannot_raise_their_own_ceiling(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)

        r = _budget(client, daily_token_cap=500_000)

        assert r.status_code == 403
        assert "somebody else's money" in r.json()["detail"]
        assert "can only be lowered" in r.json()["detail"]

    def test_a_user_on_the_platform_key_may_lower_their_own_ceiling(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)

        assert _budget(client, daily_token_cap=10_000).status_code == 200
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (10_000, "user")

    def test_a_user_on_the_platform_key_cannot_go_unlimited(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)

        r = _budget(client, daily_token_cap=0)

        assert r.status_code == 403

    def test_a_user_with_their_own_key_may_raise_it(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        assert _put(client).status_code == 200

        assert _budget(client, daily_token_cap=5_000_000).status_code == 200
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (5_000_000, "user")

    def test_a_user_with_their_own_key_may_go_unlimited(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        _put(client)

        assert _budget(client, daily_token_cap=0).status_code == 200

    def test_a_department_key_above_a_user_does_not_let_that_user_raise_their_own(self, client, act_as, db, platform_key, monkeypatch):
        """The department is paying, so the ceiling is the department's to move."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        assert _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY).status_code == 200
        act_as(**MEMBER)

        r = _budget(client, daily_token_cap=500_000)

        assert r.status_code == 403

    def test_a_department_without_a_key_cannot_raise_its_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)

        r = _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=900_000)

        assert r.status_code == 403
        assert "This department has" in r.json()["detail"]

    def test_a_department_without_a_key_may_lower_its_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)

        assert _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=40_000).status_code == 200

    def test_a_department_with_its_own_key_may_raise_its_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)

        assert _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=900_000).status_code == 200
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (900_000, "department")

    def test_a_user_under_a_raised_department_allowance_inherits_it_without_a_key(self, client, act_as, db, platform_key, monkeypatch):
        """Inheriting a bigger allowance is not the same as raising one. The department
        is paying either way."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=900_000)
        act_as(**MEMBER)

        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (900_000, "department")
        # And the user may still set a lower one of their own against that inherited ceiling.
        assert _budget(client, daily_token_cap=800_000).status_code == 200

    def test_a_platform_admin_may_raise_anyones_allowance(self, client, act_as, db, platform_key, monkeypatch):
        """They are the one paying for the platform key."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**PLATFORM)

        assert _budget(client, daily_token_cap=0, owner_user_id=10).status_code == 200
        assert _budget(client, scope="platform", daily_token_cap=900_000).status_code == 200

    def test_only_a_platform_admin_may_set_the_platform_allowance(self, client, act_as, db, platform_key):
        act_as(**DEPT_ADMIN)
        r = _budget(client, scope="platform", daily_token_cap=10)
        assert r.status_code == 403
        assert "Only a platform admin" in r.json()["detail"]

    def test_raising_is_judged_against_what_would_be_inherited_not_the_current_row(self, client, act_as, db, platform_key, monkeypatch):
        """Someone who lowered their own cap can put it back, because the ceiling that
        matters is the one above them, not the one they set yesterday."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        assert _budget(client, daily_token_cap=10_000).status_code == 200

        assert _budget(client, daily_token_cap=90_000).status_code == 200
        assert _budget(client, daily_token_cap=100_001).status_code == 403


class TestBudgetAccess:
    def test_someone_else_cannot_set_your_allowance(self, client, act_as, db, platform_key):
        act_as(**OTHER_MEMBER)
        r = _budget(client, daily_token_cap=1, owner_user_id=10)
        assert r.status_code == 403

    def test_an_admin_of_another_department_cannot_set_this_ones(self, client, act_as, db, platform_key):
        act_as(**OTHER_DEPT_ADMIN)
        r = _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=1)
        assert r.status_code == 403

    def test_a_department_allowance_needs_a_dept_id(self, client, act_as, db, platform_key):
        act_as(**DEPT_ADMIN)
        r = _budget(client, scope=SCOPE_DEPARTMENT, daily_token_cap=1)
        assert r.status_code == 422

    def test_listing_shows_your_own_your_departments_and_the_platforms(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**PLATFORM)
        _budget(client, scope="platform", daily_token_cap=90_000)
        _budget(client, daily_token_cap=1_000, owner_user_id=11)
        act_as(**DEPT_ADMIN)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=80_000)
        act_as(**MEMBER)
        _budget(client, daily_token_cap=70_000)

        items = client.get("/settings/credentials/budgets").json()["items"]

        assert {(i["scope"], i["daily_token_cap"]) for i in items} == {
            ("platform", 90_000), ("department", 80_000), ("user", 70_000),
        }

    def test_deleting_your_own_allowance_restores_what_it_overrode(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        row = _budget(client, daily_token_cap=10_000).json()

        assert client.delete(f"/settings/credentials/budgets/{row['id']}").status_code == 204
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (100_000, "platform_default")

    def test_you_cannot_delete_someone_elses_allowance(self, client, act_as, db, platform_key):
        act_as(**PLATFORM)
        row = _budget(client, daily_token_cap=1, owner_user_id=11).json()
        act_as(**MEMBER)

        assert client.delete(f"/settings/credentials/budgets/{row['id']}").status_code == 404

    def test_only_a_platform_admin_may_delete_the_platform_allowance(self, client, act_as, db, platform_key):
        act_as(**PLATFORM)
        row = _budget(client, scope="platform", daily_token_cap=1).json()
        act_as(**DEPT_ADMIN)

        assert client.delete(f"/settings/credentials/budgets/{row['id']}").status_code == 403

    def test_a_missing_allowance_is_404(self, client, act_as, db, platform_key):
        act_as(**MEMBER)
        assert client.delete("/settings/credentials/budgets/9999").status_code == 404

    def test_the_effective_endpoint_says_the_cap_and_where_it_came_from(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=900_000)
        act_as(**MEMBER)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=10, tokens=1_234))
        db.commit()

        body = client.get("/settings/credentials/budgets/effective").json()

        assert body == {
            "daily_token_cap": 900_000, "source": "department",
            "inherited_cap": 900_000, "inherited_source": "department",
            "tokens_used_today": 1_234, "may_raise": False, "show_figures": True,
        }

    def test_a_user_under_a_department_key_sees_the_figures_without_being_able_to_raise_the_cap(self, client, act_as, db, platform_key, monkeypatch):
        """The two fields answer different questions. The department's money is not this
        person's to spend more of, but it is being spent on them."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        act_as(**MEMBER)

        body = client.get("/settings/credentials/budgets/effective").json()

        assert body["may_raise"] is False
        assert body["show_figures"] is True
        # The same answer the refusal path gives, because both read one function.
        resolved = credentials_service.resolve_for_user_id(db, 10, dept_ids=(DEPT,))
        assert llm_budget.may_see_figures(resolved) is True

    def test_a_user_on_the_platform_key_gets_neither(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)

        body = client.get("/settings/credentials/budgets/effective").json()

        assert body["may_raise"] is False and body["show_figures"] is False

    def test_the_effective_endpoint_says_when_you_may_raise_it(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        _put(client)

        body = client.get("/settings/credentials/budgets/effective").json()

        assert body["may_raise"] is True and body["show_figures"] is True
        assert body["source"] == "platform_default" and body["daily_token_cap"] == 100_000

    def test_the_budget_routes_need_a_login(self, client):
        assert client.get("/settings/credentials/budgets").status_code == 401
        assert client.put("/settings/credentials/budgets", json={"scope": "user", "daily_token_cap": 1}).status_code == 401
        assert client.get("/settings/credentials/budgets/effective").status_code == 401
        assert client.delete("/settings/credentials/budgets/1").status_code == 401

    def test_a_negative_allowance_is_refused_by_the_schema(self, client, act_as, db, platform_key):
        act_as(**MEMBER)
        assert _budget(client, daily_token_cap=-1).status_code == 422


class TestBudgetIsEnforced:
    def test_a_lowered_user_cap_refuses_a_call_the_platform_cap_would_have_allowed(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        _budget(client, daily_token_cap=1_000)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=10, tokens=1_500))
        db.commit()

        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, dept_ids=(DEPT,))

    def test_a_raised_department_cap_lets_a_call_through_the_platform_cap_would_refuse(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1_000)
        act_as(**DEPT_ADMIN)
        _put(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, key=DEPT_KEY)
        _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=500_000)
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=10, tokens=5_000))
        db.commit()

        llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, dept_ids=(DEPT,))
        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT)


class TestTokenEstimate:
    """No tokeniser is installed, so this is a measured approximation. What matters is
    that it never comes in under what the provider bills."""

    def test_it_counts_every_input(self):
        one = llm_budget.estimate_tokens(["x" * 260])
        two = llm_budget.estimate_tokens(["x" * 260, "y" * 260])
        assert two > one

    def test_a_bare_string_is_treated_as_one_input(self):
        assert llm_budget.estimate_tokens("x" * 260) == llm_budget.estimate_tokens(["x" * 260])

    def test_a_short_input_still_costs_something(self):
        """A nine-character file was billed 5 tokens by the provider. Pricing it at zero
        is how a thousand tiny files slip past a cap."""
        assert llm_budget.estimate_tokens(["body a.py"]) >= 5

    def test_empty_input_costs_nothing(self):
        assert llm_budget.estimate_tokens([]) == 0

    @pytest.mark.parametrize("text,billed", [
        # Real inputs and what OpenAI really charged for them, taken from the thinnest
        # margins found across 500 chunks. The requirements line is the case that broke a
        # character-count estimator: eleven characters, eight tokens.
        ("amqp==5.3.1\nasgiref==3.11.0\nbilliard==4.2.4\nboto3==1.43.46\n", 30),
        ("insert into post (title, body) values ('test title', 'test body');", 20),
        ("\u8a31\u90b1\u7fd4\nAMQP\nAdriaenssens\nAdrien\nAgris\n", 20),
        ("def wraps(fn):\n    return functools.wraps(fn)\n", 14),
    ])
    def test_it_stays_above_what_the_provider_billed_for_real_inputs(self, text, billed):
        assert llm_budget.estimate_tokens([text]) > billed

    def test_punctuation_costs_more_than_the_same_length_of_prose(self):
        """The reason a single characters-per-token divisor cannot work: these are the
        same length and the provider charges very different amounts for them."""
        pinned = "amqp==5.3.1 boto3==1.43.46 click==8.4.0 celery==5"
        prose = "the quick brown fox jumps over the lazy dog again"
        assert len(pinned) == len(prose)
        assert llm_budget.estimate_tokens([pinned]) > llm_budget.estimate_tokens([prose])

    def test_characters_outside_ascii_are_charged_for(self):
        assert llm_budget.estimate_tokens(["\u8a31\u90b1\u7fd4"]) > llm_budget.estimate_tokens(["abc"])

    def test_a_refusal_before_spending_says_so_rather_than_claiming_the_cap_is_spent(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1_000)
        own = ResolvedCredential(source="user", provider=PROVIDER_OPENAI, key="sk-x", model=None, bypass_token_cap=False)
        with pytest.raises(BudgetExceededError) as caught:
            llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, credential=own, estimated_tokens=5_000)
        message = str(caught.value)
        assert "This needs about 5,000 tokens" in message
        assert "1,000 of your 1,000 daily AI tokens left" in message

    def test_an_estimate_that_fits_is_allowed(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1_000)
        llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, estimated_tokens=1_000)
        with pytest.raises(BudgetExceededError):
            llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, estimated_tokens=1_001)

    def test_an_own_key_that_bypasses_the_cap_skips_the_estimate_too(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 1)
        own = ResolvedCredential(source="user", provider=PROVIDER_OPENAI, key="sk-x",
                                 model=None, bypass_token_cap=True)
        llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, credential=own, estimated_tokens=10_000_000)


class TestBudgetEdges:
    def test_tightening_an_unlimited_inherited_allowance_needs_no_key(self, client, act_as, db, platform_key, monkeypatch):
        """Inherited unlimited, so any number is a tightening and nobody has to be paying
        for it."""
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 0)
        act_as(**MEMBER)

        assert _budget(client, daily_token_cap=5_000).status_code == 200
        assert credentials_service.is_more_permissive(5_000, 0) is False
        assert credentials_service.is_more_permissive(0, 0) is False

    def test_a_platform_admin_sees_every_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**MEMBER)
        _budget(client, daily_token_cap=1_000)
        act_as(**OTHER_DEPT_ADMIN)
        _budget(client, daily_token_cap=2_000)
        act_as(**PLATFORM)

        items = client.get("/settings/credentials/budgets").json()["items"]

        assert sorted(i["owner_user_id"] for i in items) == [10, 31]

    def test_a_department_admin_can_delete_their_departments_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        row = _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=10_000).json()

        assert client.delete(f"/settings/credentials/budgets/{row['id']}").status_code == 204
        assert credentials_service.resolve_cap(db, 10, dept_ids=(DEPT,)) == (100_000, "platform_default")

    def test_a_member_cannot_delete_their_departments_allowance(self, client, act_as, db, platform_key, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 100_000)
        act_as(**DEPT_ADMIN)
        row = _budget(client, scope=SCOPE_DEPARTMENT, dept_id=DEPT, daily_token_cap=10_000).json()
        act_as(**MEMBER)

        # Readable, because it spends on their behalf. Not writable.
        assert client.delete(f"/settings/credentials/budgets/{row['id']}").status_code == 403


class TestRefusalCopy:
    """Meaning for users, mechanism for whoever pays. A token is the model vendor's unit
    of accounting; somebody trying to get an answer has no use for it, and somebody
    reconciling an invoice has no use for anything else."""

    PLATFORM = ResolvedCredential(source="platform", provider=PROVIDER_OPENAI, key="sk-p", model=None, bypass_token_cap=False)
    OWN = ResolvedCredential(source="user", provider=PROVIDER_OPENAI, key="sk-u", model=None, bypass_token_cap=False)
    DEPARTMENT = ResolvedCredential(source="department", provider=PROVIDER_OPENAI, key="sk-d", model=None, bypass_token_cap=False)

    def _spend(self, db, tokens):
        db.add(LlmUsage(report_id=None, kind=LLM_KIND_CHAT, user_id=10, tokens=tokens))
        db.commit()

    def _refusal(self, db, **kwargs):
        with pytest.raises(BudgetExceededError) as caught:
            llm_budget.check_budget(db, 10, kind=LLM_KIND_CHAT, **kwargs)
        return caught.value

    def test_someone_on_the_platform_key_is_told_the_allowance_is_used_not_the_count(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 1_259_779)

        message = str(self._refusal(db, credential=self.PLATFORM))

        assert message == "You have used today's AI allowance. The allowance resets at 00:00 UTC."
        assert "1,259,779" not in message and "200,000" not in message

    def test_the_same_holds_with_no_credential_resolved_at_all(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 500_000)

        assert "tokens" not in str(self._refusal(db))

    def test_a_call_too_large_for_what_is_left_says_that_rather_than_a_number(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 100)

        message = str(self._refusal(db, credential=self.PLATFORM, estimated_tokens=500_000))

        assert message == "This is larger than the AI allowance you have left today. The allowance resets at 00:00 UTC."

    def test_someone_paying_with_their_own_key_gets_the_figures(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 1_259_779)

        message = str(self._refusal(db, credential=self.OWN))

        assert message == "You have used 1,259,779 of your 200,000 daily AI tokens. The allowance resets at 00:00 UTC."

    def test_a_department_funding_its_own_usage_gets_the_figures(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 300_000)

        assert "300,000 of your 200,000 daily AI tokens" in str(self._refusal(db, credential=self.DEPARTMENT))

    def test_a_platform_admin_gets_the_figures_because_the_platform_spend_is_theirs(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 300_000)

        message = str(self._refusal(db, credential=self.PLATFORM, is_platform_admin=True))

        assert "300,000 of your 200,000 daily AI tokens" in message

    def test_the_numbers_stay_on_the_exception_whatever_the_wording(self, db, monkeypatch):
        monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_CAP_PER_USER", 200_000)
        self._spend(db, 250_000)

        exc = self._refusal(db, credential=self.PLATFORM, estimated_tokens=9)

        assert (exc.used, exc.cap, exc.about_to_spend, exc.remaining) == (250_000, 200_000, 9, 0)
        assert exc.show_figures is False
