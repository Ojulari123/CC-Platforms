def test_root_identifies_the_service(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "forge", "status": "ok"}

def test_health_checks_the_db(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "reachable"}

def test_protected_route_rejects_without_auth(client):
    r = client.get("/_whoami")
    assert r.status_code == 401

def test_protected_route_reads_claims_when_authed(client, act_as):
    act_as(42)
    r = client.get("/_whoami")
    assert r.status_code == 200
    assert r.json() == {"user_id": 42}
