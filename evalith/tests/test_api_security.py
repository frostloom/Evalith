from fastapi.testclient import TestClient


def test_untrusted_host_is_rejected(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 403
    assert response.json()["code"] == "untrusted_host"


def test_loopback_host_is_accepted(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "127.0.0.1:8090"})
    assert response.status_code == 200


def test_untrusted_origin_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "untrusted_origin"


def test_loopback_origin_is_accepted(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"origin": "http://127.0.0.1:8090"}
    )
    assert response.status_code == 200
