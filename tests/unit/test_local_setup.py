import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from brandpilot.settings import AppSettings
from scripts import local_setup


class LocalSetupTests(unittest.TestCase):
    def test_init_creates_valid_unique_offline_settings_without_revealing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / '.env', Path(directory) / 'second.env'
            output = io.StringIO()
            with patch('sys.argv', ['local_setup.py', 'init', '--env-file', str(first)]), contextlib.redirect_stdout(output):
                self.assertEqual(local_setup.main(), 0)
            local_setup.initialize(second)
            values = local_setup.env_values(first)
            settings = AppSettings.from_env(values)
            self.assertEqual(settings.runtime.execution_mode.value, 'offline_test')
            self.assertFalse(settings.session_cookie_secure)
            self.assertEqual(len(base64.urlsafe_b64decode(values['BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY'])), 32)
            for name in ('BRANDPILOT_APP_SECRET_KEY', 'BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY', 'BRANDPILOT_OWNER_SETUP_TOKEN', 'BRANDPILOT_HERMES_SERVICE_KEY'):
                self.assertNotIn(values[name], output.getvalue())
                self.assertNotEqual(values[name], local_setup.env_values(second)[name])

    def test_init_never_replaces_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('existing-secret=keep-me\n', encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'left unchanged'):
                local_setup.initialize(path)
            self.assertEqual(before, path.read_bytes())

    def test_https_init_sets_secure_cookies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            local_setup.initialize(path, https=True)
            self.assertTrue(AppSettings.from_env(local_setup.env_values(path)).session_cookie_secure)

    def test_update_preserves_secrets_comments_and_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('# keep comment\nGEMINI_API_KEY=not-a-real-key\nBRANDPILOT_HERMES_PYTHON=\n', encoding='utf-8')
            local_setup.update_env(path, {'BRANDPILOT_HERMES_PYTHON': 'C:\\Runtime With Spaces\\python.exe'})
            self.assertEqual(local_setup.env_values(path)['GEMINI_API_KEY'], 'not-a-real-key')
            self.assertIn('# keep comment\n', path.read_text())
            self.assertEqual(local_setup.env_values(path)['BRANDPILOT_HERMES_PYTHON'], 'C:\\Runtime With Spaces\\python.exe')

    def test_ambiguous_or_multiline_configuration_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            for content, value in [('SCOPE=a\nSCOPE=b\n', 'c'), ('SCOPE=a\n', 'c\nINJECTED=value')]:
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        local_setup.update_env(path, {'SCOPE': value})
                    self.assertEqual(before, path.read_bytes())

    def test_workspace_selection_does_not_guess_or_accept_unknown_ids(self):
        one, two = '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'
        self.assertEqual(local_setup.choose_workspace([one], None), one)
        self.assertEqual(local_setup.choose_workspace([one, two], two), two)
        for ids, requested in [([], None), ([one, two], None), ([one], two), ([one], 'invalid')]:
            with self.subTest(ids=ids, requested=requested), self.assertRaises(ValueError):
                local_setup.choose_workspace(ids, requested)

    def test_workspace_lookup_reads_configured_database_without_creating_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'local.sqlite'
            selected = '00000000-0000-4000-8000-000000000001'
            with contextlib.closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('CREATE TABLE workspaces (id TEXT PRIMARY KEY)')
                connection.execute('INSERT INTO workspaces VALUES (?)', (selected,))
            path = Path(directory) / '.env'
            path.write_text(f'BRANDPILOT_DATABASE_URL=sqlite:///{database.as_posix()}\n', encoding='utf-8')
            self.assertEqual(local_setup.workspace_id(path, None), selected)
            with contextlib.closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM workspaces').fetchone()[0], 1)

    def test_hermes_discovers_both_prepared_homes_and_checks_source_pin(self):
        for home in ('bootstrap', 'spike-bootstrap'):
            with self.subTest(home=home), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                checkout = root / '.dependencies/hermes-agent'
                (checkout / '.git').mkdir(parents=True)
                (root / 'infra/hermes').mkdir(parents=True)
                (root / 'infra/hermes/pin.json').write_text(json.dumps({'commit': 'expected-pin'}))
                key = hashlib.sha256(str(checkout.resolve()).encode()).hexdigest()[:16]
                facts = root / '.runtime/hermes' / home / 'installs' / key / 'facts.json'
                facts.parent.mkdir(parents=True)
                interpreter = root / 'prepared runtime/Scripts/python.exe'
                interpreter.parent.mkdir(parents=True)
                interpreter.touch()
                facts.write_text(json.dumps({'packages': {'venv': {'environment': str(interpreter.parent.parent)}}}))
                with patch.object(local_setup.subprocess, 'run', return_value=SimpleNamespace(stdout='expected-pin\n')):
                    self.assertEqual(local_setup.hermes_python(root), interpreter.resolve())
                with patch.object(local_setup.subprocess, 'run', return_value=SimpleNamespace(stdout='wrong-pin\n')):
                    with self.assertRaisesRegex(ValueError, 'does not match'):
                        local_setup.hermes_python(root)


if __name__ == '__main__':
    unittest.main()
