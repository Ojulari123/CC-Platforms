def _register(client, email="bob@example.com", password="Test123!password", org="Bob Co"):
    return client.post("/auth/register", json={
        "email": email,
        "password": password,
        "first_name": "Bob",
        "last_name": "Builder",
        "org_name": org,
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

    def test_duplicate_email_fails(self, client):
        _register(client)
        r = _register(client)
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"].lower()

    def test_email_is_lowercased(self, client):
        r = _register(client, email="Bob@Example.COM")
        assert r.status_code == 201
        assert r.json()["user"]["email"] == "bob@example.com"

    def test_weak_password_rejected(self, client):
        r = client.post("/auth/register", json={
            "email": "weak@example.com",
            "password": "weakpass",
            "first_name": "W",
            "last_name": "K",
            "org_name": "W Inc",
        })
        assert r.status_code == 400

    def test_invalid_email_rejected(self, client):
        r = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "Test123!password",
            "first_name": "X",
            "last_name": "Y",
            "org_name": "X Inc",
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

        # Old (now revoked) token replayed — should trigger family nuke.
        r2 = client.post("/auth/refresh", json={"refresh_token": registered_user["tokens"]["refresh_token"]})
        assert r2.status_code == 401
        assert "reuse detected" in r2.json()["detail"].lower()

        # The current-good token from the same family is now also dead.
        r3 = client.post("/auth/refresh", json={"refresh_token": new_refresh})
        assert r3.status_code == 401

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
        # Old access token should now 401 on /me (tv bumped, doesn't match DB)
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
