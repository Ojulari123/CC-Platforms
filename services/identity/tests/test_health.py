def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "identity", "status": "ok"}

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "reachable"}
