#!/usr/bin/env python3
"""Create a draft EvalGen task plan.

Only two user-facing knobs: task count and difficulty ratio. Expected-failure
tasks are included by default at 20% (at least one when count >= 5).
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

DIFFICULTIES = ('easy', 'medium', 'hard')


def parse_difficulty(value: str) -> dict[str, float]:
    parts = value.replace(':', ',').split(',')
    if len(parts) != 3:
        raise ValueError('difficulty must be three numbers, e.g. 4:4:2')
    try:
        weights = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError('difficulty must be three numbers, e.g. 4:4:2') from exc
    if any(weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError('difficulty weights must be non-negative and sum > 0')
    total = sum(weights)
    return {name: weight / total for name, weight in zip(DIFFICULTIES, weights)}


def allocate(count: int, ratios: dict[str, float]) -> dict[str, int]:
    raw = {name: count * ratios[name] for name in DIFFICULTIES}
    counts = {name: math.floor(value) for name, value in raw.items()}
    remaining = count - sum(counts.values())
    order = sorted(DIFFICULTIES, key=lambda name: (raw[name] - counts[name], -DIFFICULTIES.index(name)), reverse=True)
    for name in order[:remaining]:
        counts[name] += 1
    return counts


def build_plan(
    project: str,
    count: int,
    difficulty: str,
    failure_ratio: float,
    focus: list[str],
) -> dict:
    if count < 1:
        raise ValueError('count must be >= 1')
    if not 0 <= failure_ratio <= 1:
        raise ValueError('failure-ratio must be between 0 and 1')
    ratios = parse_difficulty(difficulty)
    difficulty_counts = allocate(count, ratios)
    failure_count = math.floor(count * failure_ratio + 0.5)
    if count >= 5 and failure_ratio > 0:
        failure_count = max(1, failure_count)
    failure_count = min(count, failure_count)
    plan_id = f"plan-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    return {
        'plan_id': plan_id,
        'project': project,
        'count': count,
        'difficulty_ratio': ratios,
        'difficulty_counts': difficulty_counts,
        'failure_ratio': failure_ratio,
        'failure_count': failure_count,
        'focus': focus,
        'approved_by_user': False,
        'approved_at': None,
        'notes': 'Draft. Confirm count/difficulty with the user, then set approved_by_user=true.',
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--count', type=int, default=50)
    parser.add_argument('--difficulty', default='4:4:2',
                        help='easy:medium:hard weights, default 4:4:2')
    parser.add_argument('--failure-ratio', type=float, default=0.2,
                        help='expected-failure share, default 0.2')
    parser.add_argument('--focus', action='append', default=[])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        plan = build_plan(args.project, args.count, args.difficulty, args.failure_ratio, args.focus)
    except ValueError as exc:
        print(f'error: {exc}')
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"count={plan['count']} difficulty={plan['difficulty_counts']} "
          f"expected_failure={plan['failure_count']}")
    print(f"plan_id={plan['plan_id']} approved_by_user=false")
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
