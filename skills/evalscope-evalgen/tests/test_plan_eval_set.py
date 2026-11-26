import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from plan_eval_set import build_plan  # noqa: E402


class PlanEvalSetTest(unittest.TestCase):
    def test_cli_default_count_is_50(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'eval_plan.json'
            subprocess.run(
                [sys.executable, str(ROOT / 'scripts' / 'plan_eval_set.py'),
                 '--project', 'project', '--out', str(out)],
                check=True, capture_output=True, text=True,
            )
            plan = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(plan['count'], 50)
        self.assertEqual(plan['difficulty_counts'], {'easy': 20, 'medium': 20, 'hard': 10})
        self.assertEqual(plan['failure_count'], 10)

    def test_default_plan_counts_and_failure_share(self):
        plan = build_plan('project', 8, '4:4:2', 0.2, [])
        self.assertEqual(plan['count'], 8)
        self.assertEqual(plan['difficulty_counts'], {'easy': 3, 'medium': 3, 'hard': 2})
        self.assertEqual(plan['failure_count'], 2)
        self.assertFalse(plan['approved_by_user'])
        self.assertTrue(plan['plan_id'].startswith('plan-'))

    def test_small_plan_has_no_failure_when_below_five(self):
        plan = build_plan('project', 1, '4:4:2', 0.2, [])
        self.assertEqual(plan['difficulty_counts'], {'easy': 1, 'medium': 0, 'hard': 0})
        self.assertEqual(plan['failure_count'], 0)

    def test_custom_difficulty_ratio(self):
        plan = build_plan('project', 6, '1:1:1', 0.2, [])
        self.assertEqual(plan['difficulty_counts'], {'easy': 2, 'medium': 2, 'hard': 2})
        self.assertEqual(plan['failure_count'], 1)

    def test_zero_failure_ratio_is_honored(self):
        plan = build_plan('project', 8, '4:4:2', 0.0, [])
        self.assertEqual(plan['failure_count'], 0)

    def test_failure_count_uses_half_up_rounding(self):
        plan = build_plan('project', 5, '1:1:1', 0.5, [])
        self.assertEqual(plan['failure_count'], 3)

    def test_invalid_inputs_fail(self):
        with self.assertRaises(ValueError):
            build_plan('project', 0, '4:4:2', 0.2, [])
        with self.assertRaises(ValueError):
            build_plan('project', 5, '4:4:2', 2.0, [])
        with self.assertRaises(ValueError):
            build_plan('project', 5, '4:4', 0.2, [])
        with self.assertRaises(ValueError):
            build_plan('project', 5, '0:0:0', 0.2, [])


if __name__ == '__main__':
    unittest.main()
