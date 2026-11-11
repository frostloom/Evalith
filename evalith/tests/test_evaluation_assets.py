from __future__ import annotations

from copy import deepcopy
import time

import pytest

from conftest import create_stub_model, import_project
from evalith.evaluation_assets import EvaluationAssets
from evalith.evaluation_store import EvaluationStore
from evalith.model_gateway import ModelGateway
from evalith.service import WorkspaceError


def task_spec():
    return {"title":"Read the fixture balance", "category":"Account queries", "objective":"Use the isolated account", "kind":"conversation", "input":{"turns":["查余额"]}, "checks":[{"type":"contains", "expected":"2000"}], "rubric":"Report the synthetic balance without making changes", "source_refs":["README.md"], "uncertainties":["Fixture balance is synthetic"]}


def setup_assets(client, project_root):
    model = create_stub_model(client)
    project = import_project(client, project_root, model_config_id=model['id'], include=['README.md']).json()['project']
    service = client.app.state.service
    return EvaluationAssets(service, EvaluationStore(client.app.state.db)), project['id']


def test_generation_checks_readiness_and_freshness_before_calling_the_model(client, project_root, monkeypatch):
    assets, project_id = setup_assets(client, project_root)
    calls = []
    monkeypatch.setattr(ModelGateway, 'complete_json', lambda *_: calls.append(True))
    with pytest.raises(WorkspaceError) as blocked:
        assets.generate(project_id, count=2)
    assert blocked.value.status_code == 409 and not calls
    client.post(f'/api/projects/{project_id}/continue')
    (project_root/'README.md').write_text('Changed rule')
    with pytest.raises(WorkspaceError) as stale:
        assets.generate(project_id, count=2)
    assert stale.value.status_code == 409 and not calls


def test_generation_versions_and_cross_project_isolation(client, project_root, monkeypatch):
    assets, project_id = setup_assets(client, project_root)
    client.post(f'/api/projects/{project_id}/continue')
    monkeypatch.setattr(ModelGateway, 'complete_json', lambda *_: {'tasks':[task_spec()]})
    item = assets.generate(project_id, count=1)['items'][0]
    assert item['version'] == 1 and item['calibration_state'] == 'unverified'
    assert item['preparation_state'] == 'needs_environment'
    old_version = item['version_id']
    changed = deepcopy(item['definition']); changed['title'] = 'Updated balance case'; changed['category'] = 'Updated category'
    edited = assets.edit(project_id, item['id'], changed)
    assert edited['version'] == 2 and edited['definition']['category'] == 'Updated category'
    previous = assets.store.task_version(project_id, old_version)
    assert previous['definition']['title'] == 'Read the fixture balance'
    assert assets.list(project_id)[0]['version'] == 2
    with pytest.raises(WorkspaceError) as wrong_project:
        assets.store.task_version('another-project', old_version)
    assert wrong_project.value.status_code == 404


@pytest.mark.parametrize('change',[{'source_refs':['../../outside']},{'kind':'python_exec'}, {'checks':[]}, {'input':{'command':'rm -rf /'}}])
def test_invalid_model_assets_do_not_persist_a_partial_batch(client, project_root, monkeypatch, change):
    assets, project_id = setup_assets(client, project_root)
    client.post(f'/api/projects/{project_id}/continue')
    invalid = {**task_spec(),**change}
    monkeypatch.setattr(ModelGateway, 'complete_json', lambda *_: {'tasks':[task_spec(),invalid]})
    with pytest.raises(WorkspaceError):
        assets.generate(project_id, count=2)
    assert assets.list(project_id) == []


def test_generation_job_and_task_revision_apis(client, project_root, monkeypatch):
    assets, project_id = setup_assets(client, project_root)
    client.post(f'/api/projects/{project_id}/continue')
    with client.app.state.db.connection() as connection:
        connection.execute("UPDATE model_configs SET provider='codex_local'")
    monkeypatch.setattr(ModelGateway, 'complete_json', lambda *_: {'tasks':[task_spec()]})
    response = client.post(f'/api/projects/{project_id}/generate',json={'count':1})
    assert response.status_code == 202, response.text
    job_id=response.json()['id']
    for _ in range(60):
        job=client.get(f'/api/projects/{project_id}/jobs/{job_id}').json()
        if job['status'] in ('completed','failed'): break
        time.sleep(.02)
    assert job['status'] == 'completed',job
    items=client.get(f'/api/projects/{project_id}/tasks').json()['items']
    assert len(items)==1
    task=items[0]
    changed={**task['definition'],'title':'Edited through API'}
    edited=client.put(f'/api/projects/{project_id}/tasks/{task["id"]}',json=changed)
    assert edited.status_code==200 and edited.json()['version']==2
    history=client.get(f'/api/projects/{project_id}/tasks/{task["id"]}/versions').json()['items']
    assert len(history)==2 and history[-1]['definition']['title']=='Read the fixture balance'
    assert client.get(f'/api/projects/other/jobs/{job_id}').status_code==404
