"""Offline acceptance tests for backup: real CLI/Store/export logic, SQLite and a local bare git remote."""
import csv
from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from arxiv_digest import cli
from arxiv_digest.config import DEFAULT_CONFIG_PATH, BackupConfig, Config, load_config

# Share the SQLite store double without importing the other test module's TestCase.
_spec = importlib.util.spec_from_file_location('_push_helpers', Path(__file__).with_name('test_telegram_push.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)

NOW = helpers.NOW
HEADER = ['arxiv_id', 'title', 'categories', 'published', 'batch_id', 'pool_size', 'batch_sent',
          'pushed_at', 'label', 'label_name', 'feedback_at']


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8')


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.remote = self.tmp / 'remote.git'
        self.work = self.tmp / 'data'
        git('init', '-q', '--bare', '-b', 'main', str(self.remote))
        git('clone', '-q', str(self.remote), str(self.work))
        git('config', 'user.name', 'Offline Test', cwd=self.work)
        git('config', 'user.email', 'offline@example.invalid', cwd=self.work)
        git('checkout', '-q', '-b', 'main', cwd=self.work)
        self.store = self.seeded_store()

    # ---------------- helpers ----------------

    @staticmethod
    def seeded_store():
        """Batch 1 (pool 40) pushed 3 papers; paper 2 got ⭐, paper 3 got 👎, paper 1 no feedback."""
        store = helpers.SQLiteStore()
        raw = store.db.connection
        raw.execute('CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, paper_id INTEGER UNIQUE, '
                    'label INTEGER NOT NULL, created_at TEXT)')
        raw.execute('INSERT INTO push_batches (started_at, pool_size, sent, status) VALUES (?,?,?,?)',
                    (NOW.isoformat(' '), 40, 3, 'success'))
        titles = ['Plain title', 'Title, with "quotes"', 'Third']
        for n, title in enumerate(titles, start=1):
            paper_id = store.add_paper(n, NOW - timedelta(hours=n), title=title)
            raw.execute("UPDATE papers SET published = '2026-09-27' WHERE id = ?", (paper_id,))
            raw.execute('INSERT INTO pushes (batch_id, paper_id, chat_id, message_id, pushed_at) VALUES (1,?,?,?,?)',
                        (paper_id, '4242', 7700 + n, (NOW + timedelta(minutes=n)).isoformat(' ')))
        raw.execute("INSERT INTO feedback (paper_id, label, created_at) VALUES (2, 2, '2026-09-28 12:00:00')")
        raw.execute("INSERT INTO feedback (paper_id, label, created_at) VALUES (3, 0, '2026-09-28 12:05:00')")
        return store

    def config(self, directory=None, push='true'):
        c = helpers.CONFIG
        return Config(c.db, c.arxiv, c.telegram, c.translate, backup=BackupConfig(str(directory or self.work), push))

    def backup(self, config=None, store=None):
        store_factory = patch.object(cli, 'Store', return_value=store or self.store)
        with patch.object(cli, 'load_config', return_value=config or self.config()), store_factory as factory:
            with self.assertLogs('arxiv_digest', level='INFO') as captured:
                code = cli.main(['backup'])
        return code, '\n'.join(captured.output), factory

    def csv_bytes(self):
        return (self.work / 'pushes.csv').read_bytes()

    def rows(self):
        return list(csv.reader(io.StringIO(self.csv_bytes().decode('utf-8-sig'))))

    def commits(self, where):
        result = git('--git-dir', str(where), 'log', '--format=%s', 'main') if where == self.remote \
            else git('log', '--format=%s', cwd=where)
        return result.stdout.splitlines() if result.returncode == 0 else []

    # ---------------- R1 ----------------

    def test_R1_export_with_and_without_feedback(self):
        code, logs, _ = self.backup()
        self.assertEqual(code, 0)
        self.assertTrue(self.csv_bytes().startswith(b'\xef\xbb\xbf'))
        rows = self.rows()
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(rows[1:], [
            ['2609.00001', 'Plain title', 'cs.CL', '2026-09-27', '1', '40', '3', '2026-09-28 08:31:00', '', '', ''],
            ['2609.00002', 'Title, with "quotes"', 'cs.CL', '2026-09-27', '1', '40', '3', '2026-09-28 08:32:00',
             '2', '超想讀', '2026-09-28 12:00:00'],
            ['2609.00003', 'Third', 'cs.CL', '2026-09-27', '1', '40', '3', '2026-09-28 08:33:00',
             '0', '沒興趣', '2026-09-28 12:05:00'],
        ])
        text = self.csv_bytes().decode('utf-8-sig')
        self.assertNotIn('4242', text)
        self.assertNotIn('7701', text)

    def test_R1_stable_output(self):
        self.backup()
        first = self.csv_bytes()
        self.backup()
        self.assertEqual(self.csv_bytes(), first)

    # ---------------- R2 ----------------

    def test_R2_new_feedback_committed_and_pushed(self):
        self.assertEqual(self.backup()[0], 0)
        self.assertEqual(len(self.commits(self.remote)), 1)
        self.assertIn('推送 3 篇', self.commits(self.remote)[0])
        self.assertIn('回饋 2 篇', self.commits(self.remote)[0])
        self.store.db.connection.execute("INSERT INTO feedback (paper_id, label, created_at) VALUES (1, 1, '2026-09-29 09:00:00')")
        self.assertEqual(self.backup()[0], 0)
        self.assertEqual(len(self.commits(self.remote)), 2)
        self.assertIn('回饋 3 篇', self.commits(self.remote)[0])
        self.assertEqual(self.rows()[1][8:10], ['1', '有興趣'])

    def test_R2_no_change_no_commit(self):
        self.backup()
        code, logs, _ = self.backup()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.commits(self.work)), 1)
        self.assertEqual(len(self.commits(self.remote)), 1)

    def test_R2_only_backup_file_committed(self):
        (self.work / 'notes.txt').write_text('keep me out', encoding='utf-8')
        self.backup()
        tracked = git('ls-files', cwd=self.work).stdout.split()
        self.assertEqual(tracked, ['pushes.csv'])

    def test_R2_push_failure_recovered_later(self):
        git('remote', 'set-url', 'origin', str(self.tmp / 'missing.git'), cwd=self.work)
        code, logs, _ = self.backup()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.commits(self.work)), 1)
        self.assertEqual(self.commits(self.remote), [])
        git('remote', 'set-url', 'origin', str(self.remote), cwd=self.work)
        code, logs, _ = self.backup()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.commits(self.work)), 1)
        self.assertEqual(len(self.commits(self.remote)), 1)

    def test_R2_not_a_git_repository(self):
        plain = self.tmp / 'plain'
        plain.mkdir()
        for directory in (self.tmp / 'missing', plain):
            with self.subTest(directory=directory.name):
                code, logs, factory = self.backup(self.config(directory))
                self.assertEqual(code, 1)
                self.assertIn(directory.name, logs)
                factory.assert_not_called()

    # ---------------- R3 ----------------

    def test_R3_defaults_and_relative_dir(self):
        root = DEFAULT_CONFIG_PATH.parent
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.ini'
            path.write_text(helpers.INI, encoding='utf-8')
            self.assertEqual(load_config(path).backup.resolved(), (root.parent / 'arxiv-digest-data', True))
            path.write_text(helpers.INI + '[BACKUP]\ndir = backups/data\npush = false\n', encoding='utf-8')
            self.assertEqual(load_config(path).backup.resolved(), (root / 'backups/data', False))

    def test_R3_commit_only(self):
        code, logs, _ = self.backup(self.config(push='false'))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.commits(self.work)), 1)
        self.assertEqual(self.commits(self.remote), [])

    def test_R3_invalid_push_flag(self):
        code, logs, factory = self.backup(self.config(push='maybe'))
        self.assertEqual(code, 1)
        self.assertIn('push', logs)
        factory.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.ini'
            path.write_text(helpers.INI + '[BACKUP]\npush = maybe\n', encoding='utf-8')
            config = load_config(path)
        with patch.object(cli, 'load_config', return_value=config), patch.object(cli, 'Store', return_value=self.store), \
                patch('sys.stdout'):
            self.assertEqual(cli.main(['status']), 0)

    # ---------------- D1 ----------------

    def test_D1_registered_and_offline(self):
        config = json.loads(Path('workflow.config.json').read_text(encoding='utf-8'))
        self.assertIn('tests/test_data_backup.py', config['testFiles'])
        self.backup()
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
