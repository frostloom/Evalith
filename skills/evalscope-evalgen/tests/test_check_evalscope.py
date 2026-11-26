import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from check_evalscope import preflight_checks  # noqa: E402

SCRIPT = ROOT / 'scripts' / 'check_evalscope.py'
MINIMAL = ROOT / 'examples' / 'minimal' / 'eval_set.v1.jsonl'
MINIMAL_PROJECT = ROOT / 'examples' / 'minimal' / 'project'


def make_check(**overrides):
    values = {'id': 'c1', 'type': 'json_path', 'path': 'app/data.json', 'dsn': '', 'url': ''}
    values.update(overrides)
    return SimpleNamespace(**values)


def make_task(checks, reset_url='', materials=None):
    return SimpleNamespace(
        id='t1', checks=checks, materials=materials or [],
        exec=SimpleNamespace(reset_url=reset_url),
    )


class PreflightChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'app').mkdir()
        (self.root / 'app' / 'data.json').write_text('{"status": "ok"}', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_path_and_url(self):
        task = make_task([
            make_check(),
            make_check(id='c2', type='http_json', url='http://127.0.0.1:9201/state'),
        ])
        self.assertEqual(preflight_checks([task], self.root), [])

    def test_path_escape_fails(self):
        task = make_task([make_check(path='../outside.json')])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)

    def test_https_url_fails(self):
        task = make_task([make_check(type='http_json', url='https://127.0.0.1:9201/state')])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)

    def test_ipv6_loopback_fails(self):
        task = make_task([make_check(type='http_json', url='http://[::1]:9201/state')])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)

    def test_reset_url_must_be_loopback_http(self):
        task = make_task([make_check()], reset_url='https://localhost:9201/reset')
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)

    def test_missing_project_root_fails(self):
        with self.assertRaises(ValueError):
            preflight_checks([make_task([make_check()])], self.root / 'missing')

    def test_missing_sqlite_file_warns(self):
        task = make_task([make_check(type='sqlite', path='', dsn='agent.db')])
        warnings = preflight_checks([task], self.root)
        self.assertTrue(any('sqlite file not present yet' in warning for warning in warnings))

    def test_sensitive_check_path_fails(self):
        task = make_task([make_check(type='file_exists', path='.env.example')])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)

    def test_missing_material_fails(self):
        task = make_task([make_check()], materials=[SimpleNamespace(path='missing.txt', sha256='a' * 64)])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root, source_root=self.root)

    def test_material_check_skipped_without_source_root(self):
        task = make_task([make_check()], materials=[SimpleNamespace(path='missing.txt', sha256='a' * 64)])
        self.assertEqual(preflight_checks([task], self.root), [])

    def test_present_material_passes(self):
        task = make_task([make_check()], materials=[SimpleNamespace(path='app/data.json', sha256='a' * 64)])
        self.assertEqual(preflight_checks([task], self.root, source_root=self.root), [])

    def test_wrong_source_root_fails(self):
        task = make_task([make_check()], materials=[SimpleNamespace(path='app/data.json', sha256='a' * 64)])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root, source_root=self.root / 'app')

    def test_lookalike_http_host_fails(self):
        task = make_task([make_check(type='http_json', url='http://localhost.evil/state')])
        with self.assertRaises(ValueError):
            preflight_checks([task], self.root)


@unittest.skipUnless(importlib.util.find_spec('evalscope'), 'EvalScope is not installed in this Python')
class MinimalExampleSmokeTest(unittest.TestCase):
    def test_minimal_example_loads(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--eval-set', str(MINIMAL),
             '--project-root', str(MINIMAL_PROJECT), '--source-root', str(MINIMAL_PROJECT)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK: EvalScope project_eval loaded 1 task(s)', result.stdout)


if __name__ == '__main__':
    unittest.main()
