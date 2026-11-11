"""Evaluation asset/job routes, independent of the project conversation API."""
from __future__ import annotations

import threading
from typing import Any

from fastapi import Body, FastAPI

from .evaluation_assets import EvaluationAssets
from .evaluation_store import EvaluationStore
from .service import WorkspaceError, WorkspaceService


def install_evaluation_routes(app: FastAPI, workspace: WorkspaceService) -> None:
    store=EvaluationStore(workspace.db)
    assets=EvaluationAssets(workspace,store)
    app.state.evaluation_store=store
    app.state.evaluation_assets=assets

    @app.get('/api/projects/{project_id}/tasks')
    def tasks(project_id: str) -> dict[str,Any]:
        return {'items':assets.list(project_id)}

    @app.get('/api/projects/{project_id}/tasks/{task_id}')
    def task(project_id: str, task_id: str) -> dict[str,Any]:
        return store.get(project_id,'task',task_id)

    @app.post('/api/projects/{project_id}/tasks',status_code=201)
    def add_task(project_id: str,payload: dict[str,Any]=Body(...)) -> dict[str,Any]:
        return assets.add(project_id,payload)

    @app.get('/api/projects/{project_id}/tasks/{task_id}/versions')
    def versions(project_id: str, task_id: str) -> dict[str,Any]:
        return {'items':store.versions(project_id,task_id)}

    @app.put('/api/projects/{project_id}/tasks/{task_id}')
    def edit(project_id: str, task_id: str, payload: dict[str,Any]=Body(...)) -> dict[str,Any]:
        return assets.edit(project_id,task_id,payload)

    @app.get('/api/projects/{project_id}/jobs/{job_id}')
    def job(project_id: str,job_id: str) -> dict[str,Any]:
        return store.get(project_id,'job',job_id)

    @app.get('/api/projects/{project_id}/jobs')
    def jobs(project_id: str) -> dict[str,Any]:
        assets.list(project_id)  # Verify project identity even when no jobs exist.
        return {'items':store.list(project_id,'job')}

    def generate_job(project_id: str,payload: dict[str,Any]) -> dict[str,Any]:
        count=payload.get('count',4)
        direction=payload.get('direction','')
        if not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=12 or not isinstance(direction,str) or len(direction)>4000:
            raise WorkspaceError('生成数量为 1–12，评测方向最多 4000 字',status_code=422)
        with workspace._project_lock(project_id):
            detail=workspace.get_project_detail(project_id)
            if not detail['readiness']['generation_allowed']:
                raise WorkspaceError(detail['readiness']['reason'],status_code=409,code='generation_not_ready')
            model=workspace.gateway_for(detail['project']['model_config_id'])
            if model.config is None or model.config.provider=='stub':
                raise WorkspaceError('请先选择真实模型；离线演示不会生成真实评测资产',status_code=422,code='real_model_required')
            if any(j['status'] in ('pending','running') and j.get('operation')=='generation' for j in store.list(project_id,'job')):
                raise WorkspaceError('此项目已有题目生成任务在运行',status_code=409,code='generation_busy')
            record=store.create(project_id,'job',{'operation':'generation','count':count,'direction':workspace._scrub_saved_secrets(direction),'model':model.name,'usage':None,'result':None,'error':None})
        def execute():
            store.update(project_id,'job',record['id'],status='running')
            try:
                result=assets.generate(project_id,count=count,direction=direction)
                store.update(project_id,'job',record['id'],status='completed',usage=result['usage'],result={'task_ids':[item['id'] for item in result['items']],'generation_id':result['generation_id']})
            except Exception as exc:
                store.update(project_id,'job',record['id'],status='failed',error=workspace._scrub_saved_secrets(str(exc))[:1500])
        threading.Thread(target=execute,name='evalith-generation-'+record['id'],daemon=True).start()
        return record

    @app.post('/api/projects/{project_id}/generate',status_code=202)
    def generate(project_id: str,payload: dict[str,Any]=Body(default={})) -> dict[str,Any]:
        return generate_job(project_id,payload)

    @app.post('/api/projects/{project_id}/test-sets/generate',status_code=202)
    def generate_test_set(project_id: str,payload: dict[str,Any]=Body(default={})) -> dict[str,Any]:
        return generate_job(project_id,payload)
