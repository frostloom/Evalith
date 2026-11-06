from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_backend_image_disables_telemetry_and_platform_defaults() -> None:
    dockerfile = (REPO / "workbench/docker/backend.Dockerfile").read_text(
        encoding="utf-8"
    )
    for setting in (
        "OTEL_RHESIS_TELEMETRY_ENABLED=false",
        "OTEL_SDK_DISABLED=true",
        "ENABLE_RHESIS_KEY=false",
        "RHESIS_CONNECTOR_DISABLED=true",
    ):
        assert setting in dockerfile


def test_workbench_frontend_start_is_loopback_only() -> None:
    script = (REPO / "workbench/run_local.sh").read_text(encoding="utf-8")
    assert "npm start -- --hostname 127.0.0.1" in script
    assert "uvicorn rhesis.backend.app.main:app" in script
    assert "--host 127.0.0.1" in script
