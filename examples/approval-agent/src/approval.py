"""Synthetic release approval handler.

The implementation is deliberately incomplete: it trusts the role supplied by
the caller instead of resolving it from the authenticated user.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReleaseRequest:
    artifact_id: str
    actor: str
    role: str


def can_publish(request: ReleaseRequest) -> bool:
    return request.role == "release_manager"


def publish(request: ReleaseRequest, store: dict) -> dict:
    artifact = store.setdefault(
        request.artifact_id, {"status": "draft", "releases": []}
    )
    if not can_publish(request):
        return {"ok": False, "reason": "not a release manager"}
    artifact["status"] = "published"
    artifact["releases"].append(
        {"actor": request.actor, "role": request.role, "decision": "published"}
    )
    return {"ok": True}
