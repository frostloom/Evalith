import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'build_manifest.py'


class BuildManifestTest(unittest.TestCase):
    def test_manifest_records_versions_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scan_path = tmp_path / 'scan.json'
            eval_path = tmp_path / 'eval_set.v1.jsonl'
            out_path = tmp_path / 'manifest.json'
            scan_path.write_text(json.dumps({
                'root': '/project',
                'scope_digest': 'd' * 64,
                'files': [{'path': 'app.py', 'sha256': 'a' * 64}],
            }), encoding='utf-8')
            eval_path.write_text(json.dumps({
                'id': 't1', 'version': 2, 'materials': [{'path': 'app.py', 'sha256': 'a' * 64}],
            }) + '\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(SCRIPT), '--scan', str(scan_path),
                 '--eval-set', str(eval_path), '--out', str(out_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads(out_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['task_versions'], {'t1': 2})
            self.assertEqual(manifest['source_scope_digest'], 'd' * 64)
            self.assertEqual(manifest['task_count'], 1)
            self.assertEqual(len(manifest['eval_set_sha256']), 64)

    def test_material_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scan_path = tmp_path / 'scan.json'
            eval_path = tmp_path / 'eval_set.v1.jsonl'
            scan_path.write_text(json.dumps({
                'files': [{'path': 'app.py', 'sha256': 'a' * 64}],
                'scope_digest': 'd' * 64,
            }), encoding='utf-8')
            eval_path.write_text(json.dumps({
                'id': 't1', 'version': 1,
                'materials': [{'path': 'app.py', 'sha256': 'b' * 64}],
            }) + '\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(SCRIPT), '--scan', str(scan_path),
                 '--eval-set', str(eval_path), '--out', str(tmp_path / 'manifest.json')],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('hash mismatch', result.stdout)

    def test_malformed_jsonl_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scan_path = tmp_path / 'scan.json'
            eval_path = tmp_path / 'eval_set.v1.jsonl'
            scan_path.write_text(json.dumps({'files': [], 'scope_digest': 'd' * 64}), encoding='utf-8')
            eval_path.write_text('{"id":"t1"}\nnot json\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(SCRIPT), '--scan', str(scan_path),
                 '--eval-set', str(eval_path), '--out', str(tmp_path / 'manifest.json')],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid JSON', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def test_duplicate_ids_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scan_path = tmp_path / 'scan.json'
            eval_path = tmp_path / 'eval_set.v1.jsonl'
            scan_path.write_text(json.dumps({'files': [], 'scope_digest': 'd' * 64}), encoding='utf-8')
            eval_path.write_text(
                json.dumps({'id': 'dup', 'version': 1}) + '\n' +
                json.dumps({'id': 'dup', 'version': 2}) + '\n',
                encoding='utf-8',
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), '--scan', str(scan_path),
                 '--eval-set', str(eval_path), '--out', str(tmp_path / 'manifest.json')],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('duplicate task id', result.stdout)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
