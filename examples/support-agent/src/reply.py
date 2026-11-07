"""Synthetic support reply handler (deliberately incomplete)."""

from __future__ import annotations


def draft_reply(message: str, account: dict) -> dict:
    lowered = message.lower()
    if "refund" in lowered:
        return {
            "reply": "I can help with that. A refund will be issued.",
            "handoff": False,
            "cites_policy": False,
        }
    if "close" in lowered or "cancel" in lowered:
        return {
            "reply": "Your account has been closed.",
            "handoff": False,
            "cites_policy": False,
        }
    return {
        "reply": f"Thanks for reaching out about your {account.get('plan', 'current')} plan.",
        "handoff": False,
        "cites_policy": False,
    }
