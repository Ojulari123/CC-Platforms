def test_root_identifies_the_service(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "pulse", "status": "ok"}


def test_health_checks_the_db(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "reachable"}
