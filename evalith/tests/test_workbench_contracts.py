from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_workbench_frontend_start_is_loopback_only() -> None:
    script = (REPO / "workbench/run_local.sh").read_text(encoding="utf-8")
    assert "npm start -- --hostname 127.0.0.1" in script
    assert "uvicorn rhesis.backend.app.main:app" in script
    assert "--host 127.0.0.1" in script
