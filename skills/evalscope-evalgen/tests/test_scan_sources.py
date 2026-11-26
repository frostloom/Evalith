import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from scan_sources import _redact, scan  # noqa: E402


class ScanSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'project'
        (self.root / 'app').mkdir(parents=True)
        (self.root / 'docs').mkdir()
        (self.root / 'secrets').mkdir()
        (self.root / 'node_modules').mkdir()
        (self.root / 'app' / 'main.py').write_text(
            'api_key = "sk-should-not-leak"\nprint("ok")\n', encoding='utf-8'
        )
        (self.root / 'docs' / 'rule.md').write_text('# 状态\ncompleted 是终态\n', encoding='utf-8')
        (self.root / '.env').write_text('SECRET=1\n', encoding='utf-8')
        (self.root / 'secrets' / 'credentials.txt').write_text('token=abc\n', encoding='utf-8')
        (self.root / 'node_modules' / 'x.js').write_text('x', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_sensitive_and_default_excludes(self):
        snapshot = scan(self.root, [], [], ['docs'])
        paths = {item['path'] for item in snapshot['files']}
        self.assertIn('app/main.py', paths)
        self.assertIn('docs/rule.md', paths)
        self.assertNotIn('.env', paths)
        self.assertNotIn('node_modules/x.js', paths)
        self.assertIn('.env', snapshot['sensitive_rejected'])

    def test_redaction_and_digest_stability(self):
        first = scan(self.root, ['app'], [], [])
        second = scan(self.root, ['app'], [], [])
        main = next(item for item in first['files'] if item['path'] == 'app/main.py')
        self.assertGreaterEqual(main['redactions'], 1)
        self.assertNotIn('sk-should-not-leak', main['excerpt'])
        self.assertEqual(first['scope_digest'], second['scope_digest'])

    def test_file_limit_is_recorded(self):
        snapshot = scan(self.root, [], [], [], max_files=1)
        self.assertEqual(len(snapshot['files']), 1)
        self.assertTrue(any(item['reason'] == 'file_limit' for item in snapshot['excluded']))

    def test_symlink_is_skipped(self):
        outside = Path(self.tmp.name) / 'outside.txt'
        outside.write_text('outside', encoding='utf-8')
        os.symlink(outside, self.root / 'app' / 'linked.txt')
        snapshot = scan(self.root, ['app'], [], [])
        paths = {item['path'] for item in snapshot['files']}
        self.assertNotIn('app/linked.txt', paths)
        self.assertTrue(any(item['reason'] == 'symlink' for item in snapshot['excluded']))

    def test_knowledge_flag_and_headings(self):
        snapshot = scan(self.root, ['docs'], [], ['docs'])
        doc = next(item for item in snapshot['files'] if item['path'] == 'docs/rule.md')
        self.assertTrue(doc['knowledge'])
        self.assertEqual(doc['headings'], ['状态'])

    def test_knowledge_dir_is_scanned_without_include(self):
        snapshot = scan(self.root, ['app'], [], ['docs'])
        paths = {item['path'] for item in snapshot['files']}
        self.assertIn('docs/rule.md', paths)
        doc = next(item for item in snapshot['files'] if item['path'] == 'docs/rule.md')
        self.assertTrue(doc['knowledge'])

    def test_missing_knowledge_dir_fails(self):
        with self.assertRaises(ValueError):
            scan(self.root, ['app'], [], ['missing'])

    def test_redaction_covers_common_secret_formats(self):
        (self.root / 'app' / 'config.json').write_text(
            '{"api_key": "sk-live-1", "access_token": "ya29-two", "clientSecret": "cs-three"}\n'
            'header = "Authorization: Bearer sk-live-four"\n'
            'DB = "postgres://admin:hunter2@db:5432/prod"\n',
            encoding='utf-8',
        )
        snapshot = scan(self.root, ['app'], [], [])
        config = next(item for item in snapshot['files'] if item['path'] == 'app/config.json')
        for secret in ('sk-live-1', 'ya29-two', 'cs-three', 'sk-live-four', 'hunter2'):
            self.assertNotIn(secret, config['excerpt'])
        self.assertGreaterEqual(config['redactions'], 5)

    def test_file_limit_does_not_hide_sensitive_rejects(self):
        snapshot = scan(self.root, [], [], [], max_files=0)
        self.assertIn('.env', snapshot['sensitive_rejected'])

    def test_char_budget_marks_late_files_unsent(self):
        for name in ('a.py', 'b.py'):
            (self.root / 'app' / name).write_text('x = "1234567890"\n', encoding='utf-8')
        snapshot = scan(self.root, ['app'], [], [], max_total_chars=1)
        self.assertTrue(all(not item['sent'] for item in snapshot['files']))
        self.assertTrue(all(item['sent_reason'] == 'char_budget' for item in snapshot['files']))

    def test_char_budget_mixed_sent_and_unsent(self):
        (self.root / 'app' / 'a.py').write_text('a = "1234567890"\n', encoding='utf-8')
        (self.root / 'app' / 'b.py').write_text('b = "1234567890"\n', encoding='utf-8')
        snapshot = scan(self.root, ['app'], [], [], max_total_chars=30)
        self.assertTrue(any(item['sent'] for item in snapshot['files']))
        self.assertTrue(any(not item['sent'] and item['sent_reason'] == 'char_budget' for item in snapshot['files']))

    def test_structured_secrets_and_innocent_keys(self):
        text = (
            '{"api_keys": ["sk-live-A", "sk-live-B"]}\n'
            '{"api_key": {"raw": "sk-live-C"}}\n'
            '{"api_key":"s3cr\\"et-tail"}\n'
            'Authorization: Basic dXNlcjpwYXNz\n'
            '-----BEGIN PGP PRIVATE KEY BLOCK-----\nsecretmaterial\n'
            '-----END PGP PRIVATE KEY BLOCK-----\n'
            'postgres://admin:p@ss@db/prod\n'
            'max_tokens = 2048\n'
            'tokenizer_type = "bpe"\n'
            'token_budget: 100\n'
            'input_tokens: 12\n'
            'secretary = "Alice Smith"\n'
            'password_policy = True\n'
            'credential_rotation_days = 90\n'
        )
        redacted, hits = _redact(text)
        for secret in ('sk-live-A', 'sk-live-B', 'sk-live-C', 's3cr', 'dXNlcjpwYXNz',
                       'secretmaterial', 'p@ss'):
            self.assertNotIn(secret, redacted)
        for innocent in ('max_tokens = 2048', 'tokenizer_type = "bpe"',
                         'token_budget: 100', 'input_tokens: 12',
                         'secretary = "Alice Smith"', 'password_policy = True',
                         'credential_rotation_days = 90'):
            self.assertIn(innocent, redacted)
        self.assertGreaterEqual(hits, 6)

    def test_redaction_long_line_is_linear(self):
        start = time.perf_counter()
        redacted, hits = _redact('x' * 20_000)
        self.assertLess(time.perf_counter() - start, 1.0)
        self.assertEqual(hits, 0)
        self.assertEqual(len(redacted), 20_000)

    def test_knowledge_dir_under_excluded_component_is_scanned(self):
        (self.root / 'build' / 'kb').mkdir(parents=True)
        (self.root / 'build' / 'kb' / 'policy.md').write_text('# Policy\nrefund\n', encoding='utf-8')
        snapshot = scan(self.root, ['app'], [], ['build/kb'])
        doc = next(item for item in snapshot['files'] if item['path'] == 'build/kb/policy.md')
        self.assertTrue(doc['knowledge'])
        self.assertTrue(doc['sent'])

    def test_knowledge_file_is_scanned(self):
        (self.root / 'docs' / 'task-definitions-2026-10-12.md').write_text(
            '# Task\nrefund\n', encoding='utf-8'
        )
        snapshot = scan(self.root, ['app'], [], ['docs/task-definitions-2026-10-12.md'])
        doc = next(
            item for item in snapshot['files']
            if item['path'] == 'docs/task-definitions-2026-10-12.md'
        )
        self.assertTrue(doc['knowledge'])
        self.assertTrue(doc['sent'])

    def test_token_like_words_are_not_redacted(self):
        redacted, hits = _redact('task-definitions-2026-10-12.md')
        self.assertEqual(redacted, 'task-definitions-2026-10-12.md')
        self.assertEqual(hits, 0)

    def test_knowledge_dir_wins_file_budget(self):
        snapshot = scan(self.root, ['app'], [], ['docs'], max_files=1)
        self.assertTrue(any(item['path'] == 'docs/rule.md' and item['knowledge'] for item in snapshot['files']))

    def test_empty_knowledge_dir_fails(self):
        (self.root / 'empty-kb').mkdir()
        with self.assertRaises(ValueError):
            scan(self.root, ['app'], [], ['empty-kb'])

    def test_default_excludes_are_case_insensitive(self):
        (self.root / 'Build').mkdir()
        (self.root / 'Build' / 'lib.py').write_text('x\n', encoding='utf-8')
        snapshot = scan(self.root, [], [], [])
        paths = {item['path'] for item in snapshot['files']}
        self.assertNotIn('Build/lib.py', paths)

    def test_secret_path_is_not_emitted(self):
        (self.root / 'api_key=sk-live-FILENAMESECRET.txt').write_text('clean\n', encoding='utf-8')
        snapshot = scan(self.root, [], [], [])
        self.assertFalse(any('sk-live-FILENAMESECRET' in item['path'] for item in snapshot['files']))
        self.assertIn('[REDACTED_PATH]', snapshot['sensitive_rejected'])

    def test_sensitive_include_is_rejected(self):
        with self.assertRaises(ValueError):
            scan(self.root, ['.env'], [], [])


if __name__ == '__main__':
    unittest.main()
