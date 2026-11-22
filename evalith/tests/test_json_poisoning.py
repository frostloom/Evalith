"""Review 2026-11-21 R1: strict JSON at the run-record boundary.

A sandboxed target that prints ``{"score": NaN}`` must not poison the
stored run record: the bare ``NaN`` literal is not valid JSON, and any
strict parser (browser, jq, export scripts) would then reject the whole
record. Two gates pin this:

1. ``parse_observed_json`` never turns ``NaN``/``Infinity`` literals in
   observed stdout into float values;
2. the store's ``encode_record`` refuses to serialize non-finite floats
   on every write path, so no record can be written that a strict
   parser would reject.
"""

import json

import pytest
from conftest import create_stub_model, import_project
from evalith.evaluation_runner import parse_observed_json
from evalith.evaluation_store import EvaluationStore, encode_record


def setup_store(client, root):
    model = create_stub_model(client)
    pid = import_project(
        client, root, model_config_id=model["id"], include=["README.md"]
    ).json()["project"]["id"]
    ws = client.app.state.service
    store = EvaluationStore(ws.db)
    return pid, ws, store


class TestObservedJsonParsing:
    @pytest.mark.parametrize(
        "payload", ['{"score": NaN}', '{"budget": Infinity}', '{"x": -Infinity}']
    )
    def test_non_finite_literals_are_rejected(self, payload):
        assert parse_observed_json(payload) is None

    def test_finite_json_still_parses(self):
        assert parse_observed_json('{"score": 0.5}') == {"score": 0.5}

    def test_plain_text_stays_none(self):
        assert parse_observed_json("hello world") is None

    def test_empty_stdout_stays_none(self):
        assert parse_observed_json("") is None


class TestStoreEncoding:
    def test_encode_record_rejects_nan_and_infinity(self):
        with pytest.raises(ValueError):
            encode_record({"score": float("nan")})
        with pytest.raises(ValueError):
            encode_record({"budget": float("inf")})

    def test_encode_record_accepts_normal_data(self):
        encoded = encode_record({"note": "clean", "level": 3})
        assert json.loads(encoded) == {"note": "clean", "level": 3}

    def test_stored_records_are_strict_json(self, client, project_root):
        pid, ws, store = setup_store(client, project_root)
        record = store.create(pid, "run", {"data": {"note": "clean"}})
        updated = store.mutate(
            pid,
            "run",
            record["id"],
            lambda current: {**current, "data": {**current["data"], "level": 3}},
        )
        with ws.db.connection() as connection:
            raw = connection.execute(
                "SELECT data FROM evaluation_records WHERE id=?", (record["id"],)
            ).fetchone()["data"]
        json.loads(raw)
        assert updated["data"]["level"] == 3
