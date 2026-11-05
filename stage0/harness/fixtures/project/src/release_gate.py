"""Toy release-gate implementation for the synthetic stage 0 project.

This module is not used by the containerised agent (the agent reimplements the same
toy rule in a deliberately naive way so the harness can produce a realistic failure).
It exists so the project fixture has a source tree and a policy-shaped implementation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Artifact:
    artifact_id: str
    status: str = "draft"
    approvals: List[Dict[str, str]] = field(default_factory=list)
    audit: List[Dict[str, Any]] = field(default_factory=list)


def is_release_manager(approval: Dict[str, str]) -> bool:
    return approval.get("role") == "release_manager"


def request_release(artifact: Artifact, actor: str) -> bool:
    """Return True only when a release_manager approved this artifact.

    This is the intended rule. The containerised agent in ``agent/agent.py``
    intentionally checks only that the actor appears in the approvals list, so a
    contributor approval is enough there. The difference is what the independent
    verifier catches.
    """
    approved = any(a.get("actor") == actor and is_release_manager(a) for a in artifact.approvals)
    if not approved:
        return False
    artifact.status = "released"
    artifact.audit.append({"action": "release", "actor": actor})
    return True
