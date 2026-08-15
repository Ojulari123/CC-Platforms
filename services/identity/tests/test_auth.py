def _register(client, email="bob@example.com", password="Test123!password", department="Bob Co"):
    return client.post("/auth/register", json={
        "email": email,
        "password": password,
        "first_name": "Bob",
        "last_name": "Builder",
        "dept_name": department,
    })

class TestRegister:
    def test_creates_user_and_returns_token_pair(self, client):
        r = _register(client)
        assert r.status_code == 201
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["email"] == "bob@example.com"
        assert body["user"]["first_name"] == "Bob"

    def test_first_user_becomes_platform_admin_and_department_admin(self, client):
        r = _register(client)
        me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
        assert me["is_platform_admin"] is True
        assert me["memberships"][0]["role"] == "admin"
        assert me["memberships"][0]["dept_name"] == "Bob Co"

    def test_second_registration_is_closed(self, client):
        _register(client)
        r = _register(client, email="someone-else@example.com")
        assert r.status_code == 403
        assert "closed" in r.json()["detail"].lower()

    def test_closed_even_for_the_same_email(self, client):
        _register(client)
        r = _register(client)
        assert r.status_code == 403

    def test_signed_up_user_does_not_close_bootstrap(self, client):
        # A non-admin signup arriving BEFORE any admin must not brick register:
        # the gate is a platform admin existing, not any user at all.
        signup = client.post("/auth/signup", json={
            "email": "early@example.com",
            "password": "Test123!password",
            "first_name": "Early",
            "last_name": "Bird",
        })
        assert signup.status_code == 201, signup.text
        r = _register(client, email="admin@example.com")
        assert r.status_code == 201, r.text
        me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
        assert me["is_platform_admin"] is True
        assert me["memberships"][0]["role"] == "admin"

    def test_email_is_lowercased(self, client):
        r = _register(client, email="Bob@Example.COM")
        assert r.status_code == 201
        assert r.json()["user"]["email"] == "bob@example.com"

    def test_weak_password_rejected_on_bootstrap(self, client):
        r = client.post("/auth/register", json={
            "email": "weak@example.com",
            "password": "weakpass",
            "first_name": "W",
            "last_name": "K",
            "dept_name": "W Inc",
        })
        assert r.status_code == 400

    def test_invalid_email_rejected_on_bootstrap(self, client):
        r = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "Test123!password",
            "first_name": "X",
            "last_name": "Y",
            "dept_name": "X Inc",
        })
        assert r.status_code == 422

class TestLogin:
    def test_success_returns_pair(self, client, registered_user):
        r = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["email"] == registered_user["email"]

    def test_wrong_password_401(self, client, registered_user):
        r = client.post("/auth/login", json={"email": registered_user["email"], "password": "WrongPass1!"})
        assert r.status_code == 401

    def test_unknown_email_401(self, client):
        r = client.post("/auth/login", json={"email": "ghost@example.com", "password": "Test123!password"})
        assert r.status_code == 401

    def test_unknown_email_still_runs_verify_and_same_message(self, client, registered_user, monkeypatch):
        # Unknown email must burn a password verify (no timing enumeration) and
        # return the exact same 401 message as a wrong password.
        import app.services.auth as auth
        calls = []
        real_verify = auth.verify_password
        monkeypatch.setattr(auth, "verify_password", lambda p, h: calls.append(h) or real_verify(p, h))

        unknown = client.post("/auth/login", json={"email": "ghost@example.com", "password": "Test123!password"})
        assert unknown.status_code == 401
        assert calls == [auth._DUMMY_PASSWORD_HASH]

        wrong = client.post("/auth/login", json={"email": registered_user["email"], "password": "WrongPass1!"})
        assert unknown.json()["detail"] == wrong.json()["detail"]

    def test_email_case_insensitive(self, client, registered_user):
        r = client.post("/auth/login", json={"email": registered_user["email"].upper(), "password": registered_user["password"]})
        assert r.status_code == 200

class TestRefresh:
    def test_rotates_and_returns_new_pair(self, client, registered_user):
        old_refresh = registered_user["tokens"]["refresh_token"]
        r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert r.status_code == 200
        body = r.json()
        assert body["refresh_token"] != old_refresh
        assert body["access_token"] != registered_user["tokens"]["access_token"]

    def test_old_refresh_no_longer_usable(self, client, registered_user):
        old_refresh = registered_user["tokens"]["refresh_token"]
        client.post("/auth/refresh", json={"refresh_token": old_refresh})
        r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert r.status_code == 401

    def test_reuse_of_revoked_token_nukes_family(self, client, registered_user):
        r1 = client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})
        assert r1.status_code == 200
        new_refresh = r1.json()["refresh_token"]

        r2 = client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})
        assert r2.status_code == 401
        assert "reuse detected" in r2.json()["detail"].lower()

        r3 = client.post("/auth/refresh", json={"refresh_token": new_refresh})
        assert r3.status_code == 401

    def test_reuse_detection_kills_outstanding_access_tokens(self, client, registered_user):
        original_access = registered_user["tokens"]["access_token"]
        rotated_access = client.post(
            "/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]},
        ).json()["access_token"]
        assert client.get("/me", headers={"Authorization": f"Bearer {rotated_access}"}).status_code == 200

        client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})

        # Revoking the family has to reach access tokens too, otherwise the stolen
        # session keeps reading data until the access token expires on its own.
        for token in (original_access, rotated_access):
            r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401
            assert "revoked" in r.json()["detail"].lower()

    def test_a_signed_out_token_replayed_is_not_treated_as_theft(self, client, registered_user):
        # It was revoked without ever being rotated away, so nobody else can be holding
        # it. Reading that as reuse would bump token_version and sign the person out of
        # every other device, which is what per-device sign-out exists to avoid.
        first = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]}).json()
        assert client.post("/auth/logout", json={"refresh_token": first["refresh_token"]}).status_code == 204

        again = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert again.status_code == 401
        assert again.json()["detail"] == "Session ended. Please log in again."
        assert client.get("/me", headers={"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}).status_code == 200
        assert client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]}).status_code == 200

    def test_unknown_refresh_token_401(self, client):
        r = client.post("/auth/refresh", json={"refresh_token": "totally-bogus"})
        assert r.status_code == 401

class TestLogout:
    def test_revokes_presented_token(self, client, registered_user):
        refresh = registered_user["tokens"]["refresh_token"]
        r = client.post("/auth/logout", json={"refresh_token": refresh})
        assert r.status_code == 204
        r2 = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r2.status_code == 401

    def test_unknown_token_still_204(self, client):
        r = client.post("/auth/logout", json={"refresh_token": "never-existed"})
        assert r.status_code == 204

    def test_other_devices_are_left_alone(self, client, registered_user):
        other = client.post("/auth/login", json={
            "email": registered_user["email"], "password": registered_user["password"],
        }).json()

        assert client.post("/auth/logout", json={"refresh_token": registered_user["tokens"]["refresh_token"]}).status_code == 204

        assert client.get("/me", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 200
        assert client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 200

class TestChangePassword:
    NEW = "NewPass1!secret"

    def _change(self, client, access_token, current, new):
        return client.post(
            "/auth/change-password",
            json={"current_password": current, "new_password": new},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def test_success_returns_new_pair(self, client, registered_user):
        r = self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], self.NEW)
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] != registered_user["tokens"]["access_token"]
        assert body["refresh_token"] != registered_user["tokens"]["refresh_token"]
        assert body["expires_in"] == 15 * 60

    def test_wrong_current_password_401(self, client, registered_user):
        r = self._change(client, registered_user["tokens"]["access_token"], "WrongCurrent1!", self.NEW)
        assert r.status_code == 401
        assert "current password" in r.json()["detail"].lower()

    def test_weak_new_password_rejected(self, client, registered_user):
        r = self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], "weak")
        assert r.status_code in (400, 422)  # 422 if pydantic min_length triggers first, 400 if validate_password does

    def test_no_auth_401(self, client):
        r = client.post("/auth/change-password", json={"current_password": "x", "new_password": "AnyNew1!password"})
        assert r.status_code == 401

    def test_old_access_token_dies_after_change(self, client, registered_user):
        old_access = registered_user["tokens"]["access_token"]
        r = self._change(client, old_access, registered_user["password"], self.NEW)
        assert r.status_code == 200
        r2 = client.get("/me", headers={"Authorization": f"Bearer {old_access}"})
        assert r2.status_code == 401
        assert "revoked" in r2.json()["detail"].lower()

    def test_old_refresh_token_dies_after_change(self, client, registered_user):
        old_refresh = registered_user["tokens"]["refresh_token"]
        self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], self.NEW)
        r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert r.status_code == 401

    def test_new_password_can_log_in(self, client, registered_user):
        self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], self.NEW)
        r = client.post("/auth/login", json={"email": registered_user["email"], "password": self.NEW})
        assert r.status_code == 200

    def test_old_password_cannot_log_in(self, client, registered_user):
        self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], self.NEW)
        r = client.post("/auth/login", json={"email": registered_user["email"], "password": registered_user["password"]})
        assert r.status_code == 401

    def test_returned_new_pair_works_on_me(self, client, registered_user):
        r = self._change(client, registered_user["tokens"]["access_token"], registered_user["password"], self.NEW)
        new_access = r.json()["access_token"]
        r2 = client.get("/me", headers={"Authorization": f"Bearer {new_access}"})
        assert r2.status_code == 200

class TestLogoutAll:
    def test_kills_every_session(self, client, registered_user):
        tokens = registered_user["tokens"]
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        other = client.post("/auth/login", json={
            "email": registered_user["email"], "password": registered_user["password"],
        }).json()

        assert client.post("/auth/logout-all", headers=auth).status_code == 204

        assert client.get("/me", headers=auth).status_code == 401
        assert client.get("/me", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401

    def test_requires_auth(self, client):
        assert client.post("/auth/logout-all").status_code == 401

    def test_user_can_log_back_in_afterwards(self, client, registered_user):
        auth = {"Authorization": f"Bearer {registered_user['tokens']['access_token']}"}
        client.post("/auth/logout-all", headers=auth)
        r = client.post("/auth/login", json={
            "email": registered_user["email"], "password": registered_user["password"],
        })
        assert r.status_code == 200
        assert client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
