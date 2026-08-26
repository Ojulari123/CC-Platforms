import pytest
from fastapi import HTTPException
from app.models import DEFAULT_SYSTEM_PERSONA, PERSONA_SYSTEM_PRESETS, Persona
from app.services import persona_prompts, personas as personas_service

DEPT = 1

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
OTHER = dict(user_id=11, memberships=[{"dept_id": DEPT, "team_id": None, "role": "engineer"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)

BODY = {"name": "Standup voice", "length": "brief", "audience": "engineer", "technical_depth": "high", "formality": "casual"}

@pytest.fixture
def presets(db):
    return personas_service.seed_system_presets(db)

def _create(client, **overrides):
    body = dict(BODY)
    body.update(overrides)
    return client.post("/personas", json=body)

def _system_id(db, name=DEFAULT_SYSTEM_PERSONA):
    return db.query(Persona).filter(Persona.owner_user_id.is_(None), Persona.name == name).one().id

class TestSystemPresets:
    def test_the_three_starters_are_seeded_once(self, db, presets):
        assert [p.name for p in presets] == [p["name"] for p in PERSONA_SYSTEM_PRESETS]

        personas_service.seed_system_presets(db)
        assert db.query(Persona).filter(Persona.owner_user_id.is_(None)).count() == 3

    def test_everyone_sees_them(self, client, act_as, presets):
        act_as(**ENGINEER)
        names = [p["name"] for p in client.get("/personas").json()["items"]]
        assert names == [p["name"] for p in PERSONA_SYSTEM_PRESETS]
        assert all(p["is_system"] for p in client.get("/personas").json()["items"])

    def test_a_system_preset_cannot_be_edited(self, client, act_as, db, presets):
        act_as(**ENGINEER)
        assert client.patch(f"/personas/{_system_id(db)}", json={"length": "detailed"}).status_code == 403

    def test_a_system_preset_cannot_be_deleted(self, client, act_as, db, presets):
        act_as(**ENGINEER)
        assert client.delete(f"/personas/{_system_id(db)}").status_code == 403

    def test_not_even_a_platform_admin_may_edit_one(self, client, act_as, db, presets):
        act_as(**PLATFORM)
        assert client.patch(f"/personas/{_system_id(db)}", json={"length": "detailed"}).status_code == 403

    def test_a_system_preset_cannot_be_made_someones_default(self, client, act_as, db, presets):
        act_as(**ENGINEER)
        assert client.put(f"/personas/{_system_id(db)}/default").status_code == 403

class TestOwnPersonas:
    def test_create_returns_the_caller_as_owner(self, client, act_as):
        act_as(**ENGINEER)
        r = _create(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["owner_user_id"] == 10
        assert body["is_system"] is False
        assert body["is_default"] is False
        assert body["technical_depth"] == "high"

    def test_a_second_persona_with_the_same_name_is_refused(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client).status_code == 201
        assert _create(client).status_code == 409

    def test_two_users_may_use_the_same_name(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client).status_code == 201
        act_as(**OTHER)
        assert _create(client).status_code == 201

    def test_an_unknown_dial_value_is_refused(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client, formality="jaunty").status_code == 422

    def test_a_blank_name_is_refused(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client, name="   ").status_code == 422

    def test_update_changes_only_what_was_sent(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        body = client.patch(f"/personas/{pid}", json={"length": "detailed"}).json()
        assert body["length"] == "detailed"
        assert body["audience"] == "engineer"

    def test_renaming_onto_another_of_your_personas_is_refused(self, client, act_as):
        act_as(**ENGINEER)
        _create(client)
        second = _create(client, name="Second").json()["id"]

        assert client.patch(f"/personas/{second}", json={"name": BODY["name"]}).status_code == 409

    def test_delete_removes_it(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        assert client.delete(f"/personas/{pid}").status_code == 204
        assert client.get(f"/personas/{pid}").status_code == 404

    def test_requires_a_token(self, client):
        assert client.get("/personas").status_code == 401

class TestSomeoneElsesPersonaIs404:
    """404 rather than 403 — the same choice repositories.get_repository makes: a 403
    confirms the row exists."""

    def test_reading(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        act_as(**OTHER)
        assert client.get(f"/personas/{pid}").status_code == 404

    def test_editing(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        act_as(**OTHER)
        assert client.patch(f"/personas/{pid}", json={"length": "brief"}).status_code == 404

    def test_deleting(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        act_as(**OTHER)
        assert client.delete(f"/personas/{pid}").status_code == 404

    def test_it_is_not_in_their_list(self, client, act_as, presets):
        act_as(**ENGINEER)
        _create(client)
        act_as(**OTHER)
        assert [p["name"] for p in client.get("/personas").json()["items"]] == [p["name"] for p in PERSONA_SYSTEM_PRESETS]

class TestDefault:
    def test_setting_a_default_clears_the_previous_one(self, client, act_as, db):
        act_as(**ENGINEER)
        first = _create(client).json()["id"]
        second = _create(client, name="Second").json()["id"]

        assert client.put(f"/personas/{first}/default").status_code == 200
        assert client.put(f"/personas/{second}/default").status_code == 200

        defaults = db.query(Persona).filter(Persona.owner_user_id == 10, Persona.is_default.is_(True)).all()
        assert [p.id for p in defaults] == [second]

    def test_another_users_default_is_untouched(self, client, act_as, db):
        act_as(**ENGINEER)
        mine = _create(client).json()["id"]
        client.put(f"/personas/{mine}/default")
        act_as(**OTHER)
        theirs = _create(client).json()["id"]
        client.put(f"/personas/{theirs}/default")

        assert db.get(Persona, mine).is_default is True
        assert db.get(Persona, theirs).is_default is True

    def test_create_can_ask_to_be_the_default(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client, is_default=True).json()["is_default"] is True

    def test_update_can_promote_a_persona_to_default(self, client, act_as, db):
        act_as(**ENGINEER)
        first = _create(client, is_default=True).json()["id"]
        second = _create(client, name="Second").json()["id"]

        assert client.patch(f"/personas/{second}", json={"is_default": True}).json()["is_default"] is True
        assert db.get(Persona, first).is_default is False

    def test_setting_someone_elses_default_is_404(self, client, act_as):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        act_as(**OTHER)
        assert client.put(f"/personas/{pid}/default").status_code == 404

class TestResolvePrecedence:
    def test_an_explicit_id_wins_over_the_users_default(self, client, act_as, db, presets):
        claims = act_as(**ENGINEER)
        default_id = _create(client, name="Default", is_default=True).json()["id"]
        override_id = _create(client, name="Override").json()["id"]

        assert personas_service.resolve(db, claims, override_id).id == override_id
        assert personas_service.resolve(db, claims).id == default_id

    def test_the_users_default_wins_over_the_system_preset(self, client, act_as, db, presets):
        claims = act_as(**ENGINEER)
        default_id = _create(client, is_default=True).json()["id"]

        assert personas_service.resolve(db, claims).id == default_id

    def test_with_nothing_chosen_it_falls_back_to_concise(self, act_as, db, presets):
        claims = act_as(**ENGINEER)

        resolved = personas_service.resolve(db, claims)
        assert resolved.name == DEFAULT_SYSTEM_PERSONA
        assert resolved.owner_user_id is None

    def test_another_users_default_does_not_leak_into_the_fallback(self, client, act_as, db, presets):
        act_as(**OTHER)
        _create(client, is_default=True)
        claims = act_as(**ENGINEER)

        assert personas_service.resolve(db, claims).name == DEFAULT_SYSTEM_PERSONA

    def test_someone_elses_persona_id_is_404(self, client, act_as, db):
        act_as(**ENGINEER)
        pid = _create(client).json()["id"]
        claims = act_as(**OTHER)

        with pytest.raises(HTTPException) as exc:
            personas_service.resolve(db, claims, pid)
        assert exc.value.status_code == 404

    def test_the_fallback_materialises_concise_when_it_was_never_seeded(self, act_as, db):
        claims = act_as(**ENGINEER)
        assert db.query(Persona).count() == 0

        resolved = personas_service.resolve(db, claims)
        assert resolved.name == DEFAULT_SYSTEM_PERSONA
        assert db.query(Persona).count() == 1

class TestPersonaPrompts:
    def test_each_dial_contributes_a_phrase(self, db, presets):
        persona = Persona(
            owner_user_id=10, name="p", length="detailed", audience="executive",
            technical_depth="low", formality="formal", instructions="Mention the deadline.",
        )
        fragment = persona_prompts.describe(persona)

        assert "executive" in fragment
        assert "Go into detail" in fragment
        assert "Avoid technical terms" in fragment
        assert "Write formally" in fragment
        assert "Mention the deadline." in fragment

    def test_two_dial_settings_produce_different_fragments(self):
        brief = Persona(name="a", length="brief", audience="engineer", technical_depth="high", formality="casual")
        detailed = Persona(name="b", length="detailed", audience="executive", technical_depth="low", formality="formal")

        assert persona_prompts.describe(brief) != persona_prompts.describe(detailed)

    def test_no_persona_is_an_empty_fragment(self):
        assert persona_prompts.describe(None) == ""

    def test_freeform_guidance_is_capped(self):
        persona = Persona(name="p", length="brief", audience="manager", technical_depth="low",
                          formality="neutral", instructions="x" * 5000)

        assert persona_prompts.describe(persona).count("x") == persona_prompts.MAX_INSTRUCTIONS_CHARS

    def test_the_persona_is_appended_to_the_base_prompt_not_substituted(self):
        persona = Persona(name="p", length="brief", audience="manager", technical_depth="low", formality="neutral")
        combined = persona_prompts.apply_to_system_prompt("Do not invent work.", persona)

        assert combined.startswith("Do not invent work.")
        assert persona_prompts.describe(persona) in combined

    def test_no_persona_leaves_the_base_prompt_alone(self):
        assert persona_prompts.apply_to_system_prompt("Do not invent work.", None) == "Do not invent work."
