from dataclasses import replace

from fastapi.testclient import TestClient

from evalith.api import create_app


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


def test_untrusted_loopback_port_origin_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"origin": "http://localhost:9999"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "untrusted_origin"


def test_configured_same_origin_port_is_accepted(client: TestClient) -> None:
    response = client.get(
        "/api/health",
        headers={
            "host": "127.0.0.1:8123",
            "origin": "http://127.0.0.1:8123",
        },
    )
    assert response.status_code == 200


def test_same_host_other_port_origin_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/health",
        headers={
            "host": "127.0.0.1:8123",
            "origin": "http://127.0.0.1:8124",
        },
    )
    assert response.status_code == 403


def test_loopback_origin_is_accepted(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"origin": "http://127.0.0.1:8090"}
    )
    assert response.status_code == 200


def test_remote_client_is_rejected_without_opt_in(settings) -> None:
    app = create_app(replace(settings, allow_remote=False))
    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        response = remote.get(
            "/api/health", headers={"host": "127.0.0.1:8090"}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "remote_access_disabled"


def test_remote_client_is_allowed_with_opt_in(settings) -> None:
    app = create_app(replace(settings, allow_remote=True))
    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        response = remote.get(
            "/api/health", headers={"host": "127.0.0.1:8090"}
        )
    assert response.status_code == 200


def test_remote_opt_in_keeps_host_validation(settings) -> None:
    app = create_app(replace(settings, allow_remote=True))
    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        response = remote.get(
            "/api/health", headers={"host": "evil.example"}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "untrusted_host"


def test_remote_opt_in_keeps_origin_validation(settings) -> None:
    app = create_app(replace(settings, allow_remote=True))
    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        response = remote.get(
            "/api/health",
            headers={
                "host": "127.0.0.1:8090",
                "origin": "http://evil.example",
            },
        )
    assert response.status_code == 403
    assert response.json()["code"] == "untrusted_origin"
