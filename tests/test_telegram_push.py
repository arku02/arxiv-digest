"""Offline acceptance tests for Telegram push: real CLI/Store logic, SQLite and simulated Bot API."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import requests

from arxiv_digest import cli
from arxiv_digest.config import ArxivConfig, Config, DBConfig, TelegramConfig, load_config
from arxiv_digest.notifier import PushPaper, TelegramClient, format_message, keyboard
from arxiv_digest.store import Store


TOKEN = '123456:SECRET-TOKEN-VALUE'
NOW = datetime(2026, 9, 28, 8, 30, 0)
TELEGRAM = TelegramConfig(TOKEN, '42', '10')
CONFIG = Config(DBConfig('invalid', 'test', 'unused', 3306, 'offline'),
                ArxivConfig(['cs.CL'], 2, 4, 0, 1), TELEGRAM)
PLACEHOLDER = Config(CONFIG.db, CONFIG.arxiv,
                     TelegramConfig('YOUR_BOT_TOKEN_HERE', 'YOUR_CHAT_ID_HERE', '10'))
INI = '''[DB]
host = localhost
user = test
password = unused
port = 3306
database = offline
[ARXIV]
categories = cs.CL
'''
DATETIME_KEYS = ('started_at', 'created_at', 'finished_at', 'now', 'window_start', 'window_end')


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def execute(self, sql, args=()):
        args = tuple(a.isoformat(' ') if isinstance(a, datetime) else a for a in args)
        self.cursor.execute(sql.replace('%s', '?'), args)

    @staticmethod
    def _row(row):
        return {k: datetime.fromisoformat(v) if v and k in DATETIME_KEYS else v
                for k, v in dict(row).items()}

    def fetchone(self):
        row = self.cursor.fetchone()
        return None if row is None else self._row(row)

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]


class SQLiteConnection:
    """Run Store's push queries on SQLite; this does not certify MySQL integration."""
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            CREATE TABLE papers (id INTEGER PRIMARY KEY, arxiv_id TEXT UNIQUE, title TEXT, summary TEXT,
                published TEXT, updated TEXT, categories TEXT, link TEXT, created_at TEXT);
            CREATE TABLE authors (id INTEGER PRIMARY KEY, paper_id INTEGER, name TEXT);
            CREATE TABLE push_batches (id INTEGER PRIMARY KEY, started_at TEXT, pool_size INTEGER,
                sent INTEGER DEFAULT 0, status TEXT, error TEXT, finished_at TEXT);
            CREATE TABLE pushes (id INTEGER PRIMARY KEY, batch_id INTEGER, paper_id INTEGER UNIQUE,
                chat_id TEXT, message_id INTEGER, pushed_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE runs (id INTEGER PRIMARY KEY, window_start TEXT, window_end TEXT, started_at TEXT,
                finished_at TEXT, status TEXT, fetched INTEGER, new_count INTEGER, error TEXT);
        ''')

    def cursor(self):
        return Cursor(self.connection)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()


class SQLiteStore(Store):
    def __init__(self):
        super().__init__(CONFIG.db)
        self.db = SQLiteConnection()
        self.now = NOW

    def connect(self):
        pass

    def close(self):
        pass

    def init_schema(self):
        pass

    def db_now(self):
        return self.now

    def add_paper(self, number, created_at, *, title=None, summary='Offline sample', authors=('Example',)):
        raw = self.db.connection
        cursor = raw.execute(
            'INSERT INTO papers (arxiv_id, title, summary, categories, link, created_at) VALUES (?,?,?,?,?,?)',
            (f'2609.{number:05}', title or f'Paper {number}', summary, 'cs.CL',
             f'http://arxiv.org/abs/2609.{number:05}v2', created_at.isoformat(' ')))
        for name in authors:
            raw.execute('INSERT INTO authors (paper_id, name) VALUES (?,?)', (cursor.lastrowid, name))
        return cursor.lastrowid

    def add_batch(self, started_at, status):
        self.db.connection.execute('INSERT INTO push_batches (started_at, pool_size, status) VALUES (?,?,?)',
                                   (started_at.isoformat(' '), 0, status))

    def rows(self, sql):
        return [dict(r) for r in self.db.connection.execute(sql).fetchall()]

    def pushed_ids(self, batch_id=None):
        where = f' WHERE batch_id = {batch_id}' if batch_id else ''
        return [r['paper_id'] for r in self.rows('SELECT paper_id FROM pushes' + where + ' ORDER BY id')]


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class BotSession:
    """Simulated Bot API sendMessage endpoint."""
    def __init__(self, fail_at=None, status=200, error=None):
        self.calls, self.fail_at, self.status, self.error = [], fail_at, status, error

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        if self.fail_at is not None and len(self.calls) - 1 == self.fail_at:
            raise self.error or requests.ConnectionError(f'HTTPSConnectionPool: Max retries exceeded with url: /bot{TOKEN}/sendMessage')
        if self.status != 200:
            return Response(self.status, {'ok': False, 'description': "Forbidden: bot can't initiate conversation with a user"})
        return Response(200, {'ok': True, 'result': {'message_id': 1000 + len(self.calls)}})


class PushTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

    def push(self, store, session=None, *, config=CONFIG, seed=7, dry_run=False):
        session = session or BotSession()
        factory = lambda token, chat_id: TelegramClient(token, chat_id, session=session)
        with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'TelegramClient', side_effect=factory):
            sent = cli.run_push(config, dry_run=dry_run, rng=random.Random(seed), sleep=lambda s: None)
        return sent, session

    def main_push(self, store, session, config=CONFIG, argv=('push',)):
        factory = lambda token, chat_id: TelegramClient(token, chat_id, session=session)
        with patch.object(cli, 'load_config', return_value=config), patch.object(cli, 'Store', return_value=store), \
                patch.object(cli, 'TelegramClient', side_effect=factory), patch.object(cli.time, 'sleep'):
            with self.assertLogs('arxiv_digest', level='INFO') as captured:
                code = cli.main(list(argv))
        return code, '\n'.join(captured.output)

    def seeded_pool(self):
        """Last success at T0; 25 papers after it (2 already pushed), 5 before it."""
        store = SQLiteStore()
        t0 = NOW - timedelta(days=1)
        store.add_batch(t0, 'success')
        old = [store.add_paper(n, t0 - timedelta(hours=1)) for n in range(1, 6)]
        new = [store.add_paper(n, t0 + timedelta(minutes=n)) for n in range(6, 31)]
        for paper_id in new[:2]:
            store.db.connection.execute('INSERT INTO pushes (batch_id, paper_id, chat_id, message_id) VALUES (1,?,?,?)',
                                        (paper_id, '42', paper_id))
        return store, old, new[2:]

    # ---------------- R1 ----------------

    def test_R1_samples_limit_from_new_unpushed_pool(self):
        store, old, eligible = self.seeded_pool()
        store.add_paper(99, NOW + timedelta(minutes=1))  # after this batch started
        sent, session = self.push(store)
        self.assertEqual(sent, 10)
        expected = random.Random(7).sample(sorted(eligible), 10)
        self.assertEqual(store.pushed_ids(batch_id=2), expected)
        batch = store.rows('SELECT * FROM push_batches WHERE id = 2')[0]
        self.assertEqual((batch['pool_size'], batch['sent'], batch['status']), (23, 10, 'success'))
        self.assertEqual(batch['started_at'], NOW.isoformat(' '))

    def test_R1_small_pool_sends_all(self):
        store = SQLiteStore()
        ids = [store.add_paper(n, NOW - timedelta(hours=n)) for n in range(1, 4)]
        self.assertEqual(self.push(store)[0], 3)
        self.assertEqual(sorted(store.pushed_ids()), ids)

    def test_R1_empty_pool_sends_nothing(self):
        store = SQLiteStore()
        sent, session = self.push(store)
        self.assertEqual((sent, session.calls), (0, []))
        self.assertEqual(store.rows('SELECT status, sent, pool_size FROM push_batches'),
                         [{'status': 'success', 'sent': 0, 'pool_size': 0}])

    def test_R1_first_batch_uses_last_24_hours(self):
        store = SQLiteStore()
        recent = store.add_paper(1, NOW - timedelta(hours=2))
        store.add_paper(2, NOW - timedelta(hours=30))
        self.push(store)
        self.assertEqual(store.pushed_ids(), [recent])

    # ---------------- R2 ----------------

    def test_R2_message_content_and_buttons(self):
        summary = 'word ' * 100
        paper = PushPaper(id=7, arxiv_id='2609.00007', title='A < B &  C\n   study',
                          summary=summary, categories='cs.CL,cs.LG',
                          authors=['A1', 'A2', 'A3', 'A4', 'A5'])
        text = format_message(paper)
        self.assertTrue(text.startswith('<b>A &lt; B &amp; C study</b>\n'))
        self.assertIn('A1, A2, A3 等 5 人', text)
        self.assertIn('cs.CL, cs.LG', text)
        clipped = ' '.join(summary.split())[:300].rstrip() + '…'
        self.assertIn(clipped, text)
        self.assertNotIn(' '.join(summary.split()), text)
        self.assertIn('<a href="https://arxiv.org/abs/2609.00007">arXiv:2609.00007</a>', text)
        buttons = keyboard(7)['inline_keyboard']
        self.assertEqual([[b['text'] for b in row] for row in buttons], [['👎 沒興趣', '👍 有興趣', '⭐ 超想讀']])
        self.assertEqual([b['callback_data'] for b in buttons[0]], ['fb:7:0', 'fb:7:1', 'fb:7:2'])
        self.assertTrue(all(len(b['callback_data'].encode()) <= 64 for b in buttons[0]))

    def test_R2_short_fields_are_not_clipped_and_payload_is_html(self):
        store = SQLiteStore()
        paper_id = store.add_paper(1, NOW - timedelta(hours=1), summary='Short  abstract.', authors=('Solo',))
        _, session = self.push(store)
        url, payload = session.calls[0]
        self.assertTrue(url.endswith('/sendMessage'))
        self.assertEqual(payload['chat_id'], '42')
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertEqual(payload['link_preview_options'], {'is_disabled': True})
        self.assertEqual(payload['reply_markup'], keyboard(paper_id))
        self.assertIn('\nSolo\n', payload['text'])
        self.assertIn('Short abstract.', payload['text'])
        self.assertNotIn('…', payload['text'])
        self.assertNotIn('等', payload['text'])

    # ---------------- R3 ----------------

    def test_R3_each_send_recorded_and_not_repeated(self):
        store, _, eligible = self.seeded_pool()
        self.push(store)
        first = store.pushed_ids(batch_id=2)
        store.now = NOW + timedelta(days=1)
        fresh = [store.add_paper(n, NOW + timedelta(minutes=n)) for n in range(40, 45)]
        self.push(store)
        second = store.pushed_ids(batch_id=3)
        self.assertEqual(sorted(second), fresh)
        self.assertFalse(set(first) & set(second))
        messages = store.rows('SELECT chat_id, message_id FROM pushes WHERE batch_id = 2 ORDER BY id')
        self.assertEqual([m['message_id'] for m in messages], list(range(1001, 1011)))
        self.assertEqual({m['chat_id'] for m in messages}, {'42'})

    def test_R3_failure_mid_batch_keeps_sent_and_retries_rest(self):
        store, _, eligible = self.seeded_pool()
        code, _ = self.main_push(store, BotSession(fail_at=3))
        self.assertEqual(code, 1)
        sent = store.pushed_ids(batch_id=2)
        self.assertEqual(len(sent), 3)
        batch = store.rows('SELECT status, sent FROM push_batches WHERE id = 2')[0]
        self.assertEqual(batch, {'status': 'failed', 'sent': 3})
        store.now = NOW + timedelta(hours=1)
        self.push(store)
        retry = store.rows('SELECT pool_size FROM push_batches WHERE id = 3')[0]
        self.assertEqual(retry['pool_size'], 20)
        self.assertFalse(set(sent) & set(store.pushed_ids(batch_id=3)))

    # ---------------- R4 ----------------

    def test_R4_placeholder_credentials_fail_before_db(self):
        with patch.object(cli, 'load_config', return_value=PLACEHOLDER), \
                patch.object(cli, 'Store', side_effect=AssertionError('DB opened')) as store:
            with self.assertLogs('arxiv_digest', level='ERROR') as captured:
                self.assertEqual(cli.main(['push']), 1)
        store.assert_not_called()
        self.assertIn('config.ini', '\n'.join(captured.output))

    def test_R4_invalid_daily_limit_fails_before_db(self):
        for value in ('0', '-3', 'abc', ''):
            with self.subTest(value=value):
                config = Config(CONFIG.db, CONFIG.arxiv, TelegramConfig(TOKEN, '42', value))
                with patch.object(cli, 'load_config', return_value=config), \
                        patch.object(cli, 'Store', side_effect=AssertionError('DB opened')) as store:
                    with self.assertLogs('arxiv_digest', level='ERROR') as captured:
                        self.assertEqual(cli.main(['push', '--dry-run']), 1)
                store.assert_not_called()
                self.assertIn('daily_limit', '\n'.join(captured.output))

    def test_R4_token_is_masked_in_errors(self):
        store, _, _ = self.seeded_pool()
        code, output = self.main_push(store, BotSession(fail_at=0))
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, output)
        self.assertIn('<bot_token>', output)
        error = store.rows('SELECT error FROM push_batches WHERE id = 2')[0]['error']
        self.assertNotIn(TOKEN, error)

    def test_R4_forbidden_hints_start(self):
        store, _, _ = self.seeded_pool()
        code, output = self.main_push(store, BotSession(status=403))
        self.assertEqual(code, 1)
        self.assertIn('Start', output)
        self.assertNotIn(TOKEN, output)

    def test_R4_fetch_unaffected_by_telegram_section(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.ini'
            for extra in ('', '[TELEGRAM]\ndaily_limit = abc\n'):
                with self.subTest(extra=extra):
                    path.write_text(INI + extra, encoding='utf-8')
                    config = load_config(path)
                    with patch.object(cli, 'run_fetch', return_value=0) as fetch:
                        self.assertEqual(cli.main(['--config', str(path), 'daily']), 0)
                    fetch.assert_called_once()
            path.write_text(INI, encoding='utf-8')
            self.assertEqual(load_config(path).telegram.limit(), 10)

    # ---------------- R5 ----------------

    def test_R5_dry_run_previews_without_sending_or_recording(self):
        store, _, eligible = self.seeded_pool()
        before = store.rows('SELECT COUNT(*) AS n FROM pushes')
        output = io.StringIO()
        with patch.object(cli, 'TelegramClient', side_effect=AssertionError('Telegram used')), \
                patch.object(cli, 'Store', return_value=store), redirect_stdout(output):
            sent = cli.run_push(PLACEHOLDER, dry_run=True,
                                rng=random.Random(7), sleep=lambda s: None)
        self.assertEqual(sent, 0)
        text = output.getvalue()
        for paper_id in random.Random(7).sample(sorted(eligible), 10):
            self.assertIn(f'Paper {paper_id}<', text)
        self.assertIn('⭐ 超想讀', text)
        self.assertIn('23', text)
        self.assertEqual(store.rows('SELECT COUNT(*) AS n FROM pushes'), before)
        self.assertEqual(len(store.rows('SELECT * FROM push_batches')), 1)

    def test_R5_dry_run_cli_exit_code(self):
        store, _, _ = self.seeded_pool()
        with patch.object(cli, 'load_config', return_value=PLACEHOLDER), patch.object(cli, 'Store', return_value=store), \
                patch.object(cli, 'TelegramClient', side_effect=AssertionError('Telegram used')), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['push', '--dry-run']), 0)

    # ---------------- D1 ----------------

    def test_D1_registered_and_offline(self):
        config = json.loads(Path('workflow.config.json').read_text(encoding='utf-8'))
        self.assertIn('tests/test_telegram_push.py', config['testFiles'])
        store, _, _ = self.seeded_pool()
        self.push(store)
        self.main_push(store, BotSession(fail_at=0))
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
