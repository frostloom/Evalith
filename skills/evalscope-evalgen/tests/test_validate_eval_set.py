import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'validate_eval_set.py'


def base_task(**overrides):
    task = {
        'id': 't1',
        'version': 1,
        'question': 'q',
        'reference_answer': 'a',
        'expected_facts': ['a'],
        'pass_threshold': 0.6,
        'rubric': [
            {'id': 'c1', 'criterion': 'ok', 'weight': 1, 'must_pass': True,
             'evidence_requirement': 'outcome'},
            {'id': 'c2', 'criterion': 'explains the result', 'weight': 1,
             'must_pass': False, 'evidence_requirement': 'answer'},
        ],
        'checks': [{'id': 'chk', 'type': 'json_path', 'path': 'data.json',
                    'json_path': 'status', 'expect': 'ok'}],
        'exec': {'type': 'agent_api', 'protocol': 'rest_steps',
                 'agent_url_env': 'EVAL_AGENT_URL', 'trace': {'mode': 'auto'},
                 'session': {'id_from': 'sample_id'}},
        'source_refs': ['app.py:1'],
        'origin': 'fact',
        'materials': [],
        'metadata': {
            'source_analysis': {
                'code_refs': [{'path': 'app.py', 'line': 1, 'fact': 'entry point'}],
                'doc_refs': [],
                'facts': ['a'],
                'scope_digest': 'd' * 64,
            },
        },
    }
    task.update(overrides)
    return task


class ValidateEvalSetTest(unittest.TestCase):
    def run_validator(self, tasks, extra=()):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eval_set.v1.jsonl'
            path.write_text('\n'.join(json.dumps(task, ensure_ascii=False) for task in tasks),
                            encoding='utf-8')
            return subprocess.run(
                [sys.executable, str(SCRIPT), '--eval-set', str(path), *extra],
                capture_output=True, text=True,
            )

    def test_valid_task(self):
        result = self.run_validator([base_task()], ['--strict'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_reference_answer_fails(self):
        task = base_task()
        del task['reference_answer']
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('reference_answer', result.stdout)

    def test_rubric_without_answer_criterion_fails(self):
        task = base_task(rubric=[
            {'id': 'c1', 'criterion': 'ok', 'weight': 1, 'must_pass': True,
             'evidence_requirement': 'outcome'},
        ])
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('answer criterion', result.stdout)

    def test_https_and_ipv6_check_urls_fail(self):
        for url in ('https://127.0.0.1:9201/state', 'http://[::1]:9201/state'):
            task = base_task(checks=[{
                'id': 'chk', 'type': 'http_json', 'url': url,
                'json_path': 'ok', 'expect': True,
            }])
            result = self.run_validator([task])
            self.assertEqual(result.returncode, 1)
            self.assertIn('URL must use', result.stdout)

    def test_missing_expect_fails(self):
        task = base_task(checks=[{
            'id': 'chk', 'type': 'json_path', 'path': 'data.json', 'json_path': 'status',
        }])
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('requires expect', result.stdout)

    def test_messages_only_task_fails(self):
        task = base_task()
        del task['question']
        task['messages'] = [{'role': 'user', 'content': 'hi'}]
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('question is required', result.stdout)

    def test_unknown_fields_origin_and_trace_fail(self):
        task = base_task()
        task['bogus'] = 1
        task['origin'] = 'guess'
        task['exec']['trace']['mode'] = 'bogus'
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('unknown field', result.stdout)
        self.assertIn('origin must be fact or inference', result.stdout)
        self.assertIn('trace.mode', result.stdout)

    def test_expected_failure_requires_forbidden_facts_without_plan(self):
        task = base_task()
        task['metadata'] = {'expect_failure': True}
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected-failure task requires forbidden_facts', result.stdout)

    def test_non_object_line_fails_without_traceback(self):
        result = self.run_validator([[1, 2, 3]])
        self.assertEqual(result.returncode, 1)
        self.assertIn('task must be a JSON object', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def test_missing_scan_and_plan_files_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / 'eval_set.v1.jsonl'
            eval_path.write_text(json.dumps(base_task()) + '\n', encoding='utf-8')
            for flag in ('--scan', '--plan'):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), '--eval-set', str(eval_path),
                     flag, str(Path(tmp) / 'missing.json')],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn('file not found', result.stdout)
                self.assertNotIn('Traceback', result.stderr)

    def test_source_ref_to_unsent_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'files': [{'path': 'app.py', 'sha256': 'a' * 64, 'line_count': 1, 'sent': False}],
            }), encoding='utf-8')
            result = self.run_validator(
                [base_task(source_refs=['app.py:1'])],
                ['--scan', str(scan_path), '--no-verify-source'],
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('without an excerpt', result.stdout)

    def test_scan_entry_escape_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'files': [{'path': '../outside.txt', 'sha256': 'a' * 64, 'sent': True}],
            }), encoding='utf-8')
            result = self.run_validator(
                [base_task()],
                ['--scan', str(scan_path), '--root', str(Path(tmp) / 'root')],
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('scan entry must stay under root', result.stdout)

    def test_zero_rubric_weight_fails(self):
        task = base_task(rubric=[
            {'id': 'c1', 'criterion': 'ok', 'weight': 0, 'must_pass': True,
             'evidence_requirement': 'outcome'},
            {'id': 'c2', 'criterion': 'say', 'weight': 0, 'must_pass': False,
             'evidence_requirement': 'answer'},
        ])
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('total weight must be > 0', result.stdout)

    def test_no_verify_source_still_rejects_scan_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'files': [{'path': '../outside.txt', 'sha256': 'a' * 64, 'sent': True}],
            }), encoding='utf-8')
            result = self.run_validator([base_task()], ['--scan', str(scan_path), '--no-verify-source'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('scan entry must stay under root', result.stdout)

    def test_unhashable_fields_fail_without_traceback(self):
        task = base_task()
        task['origin'] = ['fact']
        task['rubric'][0]['id'] = ['c1']
        task['checks'][0]['type'] = ['json_path']
        task['exec']['trace']['mode'] = ['auto']
        task['id'] = ['t1']
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('origin must be fact or inference', result.stdout)

    def test_malformed_scan_and_source_analysis_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text('{"files": null}', encoding='utf-8')
            result = self.run_validator([base_task()], ['--scan', str(scan_path)])
            self.assertEqual(result.returncode, 1)
            self.assertIn('scan.files must be a list', result.stdout)
            self.assertNotIn('Traceback', result.stderr)
        task = base_task()
        task['metadata']['source_analysis']['code_refs'] = 5
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('code_refs/doc_refs must be lists', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def test_plan_approval_requires_true_and_counts_sum(self):
        task = base_task()
        task['metadata'].update({'plan_id': 'p1', 'difficulty': 'easy', 'expect_failure': False})
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 1, 'approved_by_user': 'false',
                'difficulty_counts': {'easy': 1, 'medium': 0, 'hard': 0},
                'failure_count': 0,
            }), encoding='utf-8')
            result = self.run_validator([task], ['--plan', str(plan_path)])
            self.assertEqual(result.returncode, 1)
            self.assertIn('not approved', result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 2, 'approved_by_user': True,
                'difficulty_counts': {'easy': 1, 'medium': 0, 'hard': 0},
                'failure_count': 0,
            }), encoding='utf-8')
            result = self.run_validator([task], ['--plan', str(plan_path)])
            self.assertEqual(result.returncode, 1)
            self.assertIn('difficulty_counts must sum to count', result.stdout)

    def test_plan_requires_difficulty_per_task(self):
        task = base_task()
        task['metadata'].update({'plan_id': 'p1', 'expect_failure': False})
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 1, 'approved_by_user': True,
                'difficulty_counts': {'easy': 1, 'medium': 0, 'hard': 0},
                'failure_count': 0,
            }), encoding='utf-8')
            result = self.run_validator([task], ['--plan', str(plan_path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn('metadata.difficulty must be easy/medium/hard', result.stdout)

    def test_null_fields_and_http_json_method_fail(self):
        for field in ('system', 'version', 'source_refs'):
            task = base_task()
            task[field] = None
            result = self.run_validator([task])
            self.assertEqual(result.returncode, 1)
            self.assertIn(field, result.stdout)
        task = base_task(checks=[{
            'id': 'chk', 'type': 'http_json', 'url': 'http://127.0.0.1:9201/state',
            'method': 'POST', 'json_path': 'ok', 'expect': True,
        }])
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('only supports GET', result.stdout)

    def test_url_lookalikes_fail(self):
        for url in ('HTTP://127.0.0.1:9201/state', 'http://localhost.evil/state',
                    'http://u:p@localhost:9201/state'):
            task = base_task(checks=[{
                'id': 'chk', 'type': 'http_json', 'url': url,
                'json_path': 'ok', 'expect': True,
            }])
            result = self.run_validator([task])
            self.assertEqual(result.returncode, 1)
            self.assertIn('URL must use', result.stdout)

    def test_source_analysis_is_required(self):
        task = base_task()
        task['metadata'] = {}
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('source_analysis is required', result.stdout)

    def test_sensitive_check_path_fails(self):
        task = base_task(checks=[{
            'id': 'chk', 'type': 'json_path', 'path': '.env',
            'json_path': 'status', 'expect': 'ok',
        }])
        result = self.run_validator([task])
        self.assertEqual(result.returncode, 1)
        self.assertIn('sensitive', result.stdout)

    def test_empty_file_line_ref_warns_and_strict_fails(self):
        task = base_task(source_refs=['empty.py:1'])
        task['metadata']['source_analysis']['code_refs'] = [
            {'path': 'empty.py', 'line': 1, 'fact': 'empty'},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'files': [{
                    'path': 'empty.py', 'sha256': 'a' * 64,
                    'line_count': 0, 'sent': True,
                }],
            }), encoding='utf-8')
            result = self.run_validator([task], ['--scan', str(scan_path), '--no-verify-source'])
            self.assertEqual(result.returncode, 0)
            self.assertIn('without scanned text', result.stdout)
            strict = self.run_validator(
                [task], ['--scan', str(scan_path), '--no-verify-source', '--strict'],
            )
            self.assertEqual(strict.returncode, 1)

    def test_duplicate_ids_fail(self):
        result = self.run_validator([base_task(), base_task()])
        self.assertEqual(result.returncode, 1)
        self.assertIn('duplicate task id', result.stdout)

    def test_non_loopback_reset_url_fails(self):
        result = self.run_validator([base_task(exec={
            'type': 'agent_api', 'protocol': 'rest_steps',
            'agent_url_env': 'EVAL_AGENT_URL',
            'reset_url': 'http://example.com/reset',
            'trace': {'mode': 'auto'}, 'session': {'id_from': 'sample_id'},
        })])
        self.assertEqual(result.returncode, 1)
        self.assertIn('reset_url', result.stdout)

    def test_material_mismatch_against_scan_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'files': [{'path': 'app.py', 'sha256': 'a' * 64}],
                'scope_digest': 'd' * 64,
            }), encoding='utf-8')
            result = self.run_validator(
                [base_task(materials=[{'path': 'app.py', 'sha256': 'b' * 64}])],
                ['--scan', str(scan_path)],
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('hash mismatch', result.stdout)

    def test_source_ref_out_of_range_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            project.mkdir()
            source = project / 'app.py'
            source.write_text('one\ntwo\n', encoding='utf-8')
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'root': str(project),
                'scope_digest': 'd' * 64,
                'files': [{
                    'path': 'app.py',
                    'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'line_count': 2,
                    'headings': [],
                }],
            }), encoding='utf-8')
            result = self.run_validator(
                [base_task(source_refs=['app.py:99'])],
                ['--scan', str(scan_path), '--root', str(project)],
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('line out of range', result.stdout)

    def test_source_changed_since_scan_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            project.mkdir()
            source = project / 'app.py'
            source.write_text('one\n', encoding='utf-8')
            old_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            scan_path = Path(tmp) / 'scan.json'
            scan_path.write_text(json.dumps({
                'root': str(project),
                'scope_digest': 'd' * 64,
                'files': [{'path': 'app.py', 'sha256': old_hash, 'line_count': 1, 'headings': []}],
            }), encoding='utf-8')
            source.write_text('changed\n', encoding='utf-8')
            result = self.run_validator(
                [base_task(source_refs=['app.py:1'])],
                ['--scan', str(scan_path), '--root', str(project)],
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('source changed', result.stdout)

    def test_unapproved_plan_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 1, 'approved_by_user': False,
                'difficulty_counts': {'easy': 1, 'medium': 0, 'hard': 0},
                'failure_count': 0,
            }), encoding='utf-8')
            task = base_task(metadata={
                'plan_id': 'p1', 'difficulty': 'easy', 'expect_failure': False,
            })
            result = self.run_validator([task], ['--plan', str(plan_path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn('not approved', result.stdout)

    def test_plan_difficulty_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 1, 'approved_by_user': True,
                'difficulty_counts': {'easy': 0, 'medium': 1, 'hard': 0},
                'failure_count': 0,
            }), encoding='utf-8')
            task = base_task(metadata={
                'plan_id': 'p1', 'difficulty': 'easy', 'expect_failure': False,
            })
            result = self.run_validator([task], ['--plan', str(plan_path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn('plan difficulty medium', result.stdout)

    def test_plan_failure_count_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / 'plan.json'
            plan_path.write_text(json.dumps({
                'plan_id': 'p1', 'count': 1, 'approved_by_user': True,
                'difficulty_counts': {'easy': 1, 'medium': 0, 'hard': 0},
                'failure_count': 1,
            }), encoding='utf-8')
            task = base_task(metadata={
                'plan_id': 'p1', 'difficulty': 'easy', 'expect_failure': False,
            })
            result = self.run_validator([task], ['--plan', str(plan_path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn('plan failure_count', result.stdout)


if __name__ == '__main__':
    unittest.main()
