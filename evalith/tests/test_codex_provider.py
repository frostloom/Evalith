from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalith.codex_provider import CodexClient, CodexError


def fake_cli(tmp_path: Path, body: str) -> str:
    path = tmp_path / "fake-codex"
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(0o700)
    return str(path)


def test_local_model_requires_a_completed_turn_and_collects_usage(tmp_path):
    cli = fake_cli(tmp_path, '''import json,sys
args=sys.argv[1:]
assert "--ephemeral" in args and "--ignore-user-config" in args
assert args[args.index("--model")+1] == "gpt-6-luna"
assert "features.shell_tool=false" in args
assert any("supports_websockets=false" in a for a in args)
request=sys.stdin.read()
assert "project context" in request
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":'{"ok":true}'}}))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":27,"output_tokens":5}}))
''')
    result = CodexClient(tmp_path / "runtime", binary=cli).complete(
        [{"role": "user", "content": "project context"}], model="gpt-6-luna"
    )
    assert json.loads(result.text) == {"ok": True}
    assert result.model == "gpt-6-luna"
    assert result.usage["input_tokens"] == 27
    assert result.usage["cost_usd"] is None
    assert not list((tmp_path / "runtime").glob("**/auth.json"))


@pytest.mark.parametrize("ending", ["", 'print(\'{"type":"turn.failed","error":{"message":"access denied"}}\')'])
def test_partial_output_or_failed_turn_is_not_a_success(tmp_path, ending):
    cli = fake_cli(tmp_path, 'print(\'{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}\')\n' + ending)
    with pytest.raises(CodexError):
        CodexClient(tmp_path / "runtime", binary=cli).complete([{"role": "user", "content": "x"}], model="gpt-6-luna")


def test_timeout_reaps_the_owned_process_and_keeps_a_visible_error(tmp_path):
    cli = fake_cli(tmp_path, "import time\ntime.sleep(10)\n")
    with pytest.raises(CodexError, match="超时"):
        CodexClient(tmp_path / "runtime", binary=cli, timeout=0.1).complete([{"role": "user", "content": "x"}], model="gpt-6-luna")


def test_tools_cannot_be_treated_as_a_model_response(tmp_path):
    cli = fake_cli(tmp_path, 'print(\'{"type":"item.completed","item":{"type":"command_execution","command":"touch ../outside"}}\')\nprint(\'{"type":"turn.completed"}\')\n')
    with pytest.raises(CodexError, match="工具"):
        CodexClient(tmp_path / "runtime", binary=cli).complete([{"role": "user", "content": "x"}], model="gpt-6-luna")


def test_login_status_never_returns_the_account_or_token(tmp_path):
    cli = fake_cli(tmp_path, 'print("Logged in using ChatGPT")\n')
    status = CodexClient(tmp_path / "runtime", binary=cli).status()
    assert status == {"available": True, "logged_in": True, "authentication": "chatgpt", "model": "gpt-6-luna"}


def test_local_account_configuration_does_not_require_an_api_key_or_paid_provider_switch(client, settings, monkeypatch):
    from evalith.codex_provider import ModelReply
    settings.allow_paid_models = False
    response = client.post('/api/model-configs', json={"name":"Local account", "provider":"codex_local", "model_name":"gpt-6-luna"})
    assert response.status_code == 201, response.text
    model = response.json()
    assert model['base_url'] is None and model['has_api_key'] is False
    calls = []
    def complete(self, messages, *, model):
        calls.append(model)
        return ModelReply('{"ok":true}', model, {"input_tokens":1,"output_tokens":1,"cost_usd":None})
    monkeypatch.setattr(CodexClient, 'complete', complete)
    result = client.post(f'/api/model-configs/{model["id"]}/test')
    assert result.status_code == 200 and result.json()['ok'] is True
    assert calls == ['gpt-6-luna']
    assert 'api_key' not in result.json()
    for extra in [{"api_key":"do-not-copy"}, {"base_url":"http://127.0.0.1:1"}]:
        rejected = client.post('/api/model-configs', json={"name":"wrong", "provider":"codex_local", "model_name":"gpt-6-luna", **extra})
        assert rejected.status_code == 422
