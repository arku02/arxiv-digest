"""Offline acceptance tests for feedback collection: real CLI/Store logic, SQLite and simulated Bot API."""
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from arxiv_digest import cli, notifier
from arxiv_digest.config import Config, TelegramConfig
from arxiv_digest.notifier import TelegramClient, keyboard

# Share the SQLite store double without importing the other test module's TestCase.
_spec = importlib.util.spec_from_file_location('_push_helpers', Path(__file__).with_name('test_telegram_push.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)

TOKEN, CONFIG, PLACEHOLDER, NOW = helpers.TOKEN, helpers.CONFIG, helpers.PLACEHOLDER, helpers.NOW


def click(update_id, paper_id, label, message_id, *, chat=42, data=None):
    return {'update_id': update_id, 'callback_query': {
        'id': f'cb{update_id}', 'from': {'id': chat},
        'message': {'message_id': message_id, 'chat': {'id': chat}},
        'data': data if data is not None else f'fb:{paper_id}:{label}'}}


class UpdateBot:
    """Simulated getUpdates queue with offset confirmation, plus editMessageReplyMarkup."""
    def __init__(self, updates, *, fail_get=False, edit_status=200, edit_description=''):
        self.queue, self.fail_get = list(updates), fail_get
        self.edit_status, self.edit_description = edit_status, edit_description
        self.offsets, self.edits = [], []

    def post(self, url, json, timeout):
        method = url.rsplit('/', 1)[1]
        if method == 'getUpdates':
            if self.fail_get:
                raise requests.ConnectionError(f'HTTPSConnectionPool: Max retries exceeded with url: /bot{TOKEN}/getUpdates')
            offset = json.get('offset')
            self.offsets.append(offset)
            if offset is not None:
                self.queue = [u for u in self.queue if u['update_id'] >= offset]
            return helpers.Response(200, {'ok': True, 'result': self.queue[:json['limit']]})
        if method == 'editMessageReplyMarkup':
            self.edits.append(json)
            if self.edit_status != 200:
                return helpers.Response(self.edit_status, {'ok': False, 'description': self.edit_description})
            return helpers.Response(200, {'ok': True, 'result': True})
        raise AssertionError('Unexpected Bot API method ' + method)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)
        self.store = helpers.SQLiteStore()
        self.store.db.connection.executescript('''
            CREATE TABLE feedback (id INTEGER PRIMARY KEY, paper_id INTEGER UNIQUE, label INTEGER NOT NULL,
                created_at TEXT DEFAULT '2026-09-27 16:30:00');
            CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, window_start TEXT, window_end TEXT, started_at TEXT,
                finished_at TEXT, status TEXT, fetched INTEGER, new_count INTEGER, error TEXT);
        ''')
        self.store.add_batch(NOW, 'success')
        self.papers = [self.store.add_paper(n, NOW) for n in range(1, 4)]
        for paper_id in self.papers:
            self.store.db.connection.execute(
                'INSERT INTO pushes (batch_id, paper_id, chat_id, message_id) VALUES (1,?,?,?)',
                (paper_id, '42', 100 + paper_id))

    def feedback(self):
        return {r['paper_id']: r['label'] for r in self.store.rows('SELECT paper_id, label FROM feedback')}

    def collect(self, bot, config=CONFIG):
        factory = lambda token, chat_id: TelegramClient(token, chat_id, session=bot)
        with patch.object(cli, 'Store', return_value=self.store), patch.object(cli, 'TelegramClient', side_effect=factory):
            return cli.run_collect(config)

    def main_collect(self, bot, config=CONFIG):
        factory = lambda token, chat_id: TelegramClient(token, chat_id, session=bot)
        with patch.object(cli, 'load_config', return_value=config), patch.object(cli, 'Store', return_value=self.store), \
                patch.object(cli, 'TelegramClient', side_effect=factory):
            with self.assertLogs('arxiv_digest', level='INFO') as captured:
                code = cli.main(['collect'])
        return code, captured

    # ---------------- R1 ----------------

    def test_R1_new_feedback_saved_and_acknowledged(self):
        p1 = self.papers[0]
        bot = UpdateBot([click(10, p1, 1, 101)])
        self.assertEqual(self.collect(bot), {'saved': 1, 'ignored': 0})
        self.assertEqual(self.feedback(), {p1: 1})
        self.assertEqual(bot.queue, [])
        self.assertEqual(bot.offsets, [None, 11])
        self.assertEqual(self.collect(bot), {'saved': 0, 'ignored': 0})
        self.assertEqual(self.feedback(), {p1: 1})

    def test_R1_last_click_wins(self):
        p1 = self.papers[0]
        self.collect(UpdateBot([click(1, p1, 0, 101), click(2, p1, 2, 101)]))
        self.assertEqual(self.feedback(), {p1: 2})
        self.assertEqual(len(self.store.rows('SELECT * FROM feedback')), 1)

    def test_R1_existing_feedback_is_overwritten_and_keeps_first_time(self):
        p1 = self.papers[0]
        self.store.db.connection.execute(
            "INSERT INTO feedback (paper_id, label, created_at) VALUES (?, 0, '2026-09-27 17:00:00')", (p1,))
        self.collect(UpdateBot([click(1, p1, 1, 101)]))
        self.assertEqual(self.store.rows('SELECT label, created_at FROM feedback'),
                         [{'label': 1, 'created_at': '2026-09-27 17:00:00'}])

    def test_R1_reads_multiple_batches_in_order(self):
        p1, p2, p3 = self.papers
        bot = UpdateBot([click(1, p1, 0, 101), click(2, p2, 1, 102), click(3, p3, 2, 103)])
        with patch.object(notifier, 'UPDATE_LIMIT', 2):
            self.assertEqual(self.collect(bot)['saved'], 3)
        self.assertEqual(bot.offsets, [None, 3, 4])
        self.assertEqual(self.feedback(), {p1: 0, p2: 1, p3: 2})

    # ---------------- R2 ----------------

    def test_R2_invalid_updates_are_ignored_and_acknowledged(self):
        p1, p2, _ = self.papers
        updates = [
            {'update_id': 1, 'message': {'message_id': 1, 'chat': {'id': 42}, 'text': '/start'}},
            click(2, p1, 1, 101, chat=99),
            click(3, p1, 9, 101),
            click(4, p1, 1, 101, data='hello'),
            click(5, p2, 1, 101),
            click(6, p1, 1, 999),
            click(7, p2, 2, 102),
        ]
        bot = UpdateBot(updates)
        code, captured = self.main_collect(bot)
        self.assertEqual(code, 0)
        self.assertEqual(self.feedback(), {p2: 2})
        self.assertEqual(bot.queue, [])
        self.assertIn('略過 6', '\n'.join(captured.output))

    # ---------------- R3 ----------------

    def test_R3_button_marks_current_choice(self):
        p1 = self.papers[0]
        bot = UpdateBot([click(1, p1, 1, 101)])
        self.collect(bot)
        self.assertEqual(bot.edits, [{'chat_id': '42', 'message_id': 101, 'reply_markup': keyboard(p1, selected=1)}])
        row = bot.edits[0]['reply_markup']['inline_keyboard'][0]
        self.assertEqual([b['text'] for b in row], ['👎 沒興趣', '✅ 👍 有興趣', '⭐ 超想讀'])
        self.assertEqual([b['callback_data'] for b in row], [f'fb:{p1}:0', f'fb:{p1}:1', f'fb:{p1}:2'])
        self.assertEqual(keyboard(p1), notifier.keyboard(p1, selected=None))

    def test_R3_edit_failure_only_warns(self):
        p1 = self.papers[0]
        bot = UpdateBot([click(1, p1, 2, 101)], edit_status=400, edit_description='Bad Request: message to edit not found')
        code, captured = self.main_collect(bot)
        self.assertEqual(code, 0)
        self.assertEqual(self.feedback(), {p1: 2})
        self.assertEqual(bot.queue, [])
        self.assertTrue(any(line.startswith('WARNING') for line in captured.output))

    def test_R3_not_modified_is_success(self):
        p1 = self.papers[0]
        bot = UpdateBot([click(1, p1, 1, 101)], edit_status=400,
                        edit_description='Bad Request: message is not modified: specified new message content and reply markup are exactly the same')
        code, captured = self.main_collect(bot)
        self.assertEqual(code, 0)
        self.assertFalse(any(line.startswith('WARNING') for line in captured.output))

    # ---------------- R4 ----------------

    def test_R4_database_failure_redelivers_and_is_idempotent(self):
        p1, p2, p3 = self.papers
        updates = [click(1, p1, 1, 101), click(2, p2, 0, 102), click(3, p3, 2, 103)]
        bot = UpdateBot(updates)
        real = self.store.save_feedback
        calls = []

        def flaky(paper_id, label):
            calls.append(paper_id)
            if len(calls) == 2:
                raise RuntimeError('database unavailable')
            return real(paper_id, label)

        with patch.object(self.store, 'save_feedback', side_effect=flaky):
            code, _ = self.main_collect(bot)
        self.assertEqual(code, 1)
        self.assertEqual([u['update_id'] for u in bot.queue], [1, 2, 3])
        self.assertEqual(self.collect(bot)['saved'], 3)
        self.assertEqual(self.feedback(), {p1: 1, p2: 0, p3: 2})
        self.assertEqual(len(self.store.rows('SELECT * FROM feedback')), 3)

    def test_R4_get_updates_failure_masks_token(self):
        code, captured = self.main_collect(UpdateBot([], fail_get=True))
        text = '\n'.join(captured.output)
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, text)
        self.assertIn('<bot_token>', text)
        self.assertEqual(self.feedback(), {})

    def test_R4_placeholder_credentials_fail_before_db(self):
        with patch.object(cli, 'load_config', return_value=PLACEHOLDER), \
                patch.object(cli, 'Store', side_effect=AssertionError('DB opened')) as store:
            with self.assertLogs('arxiv_digest', level='ERROR') as captured:
                self.assertEqual(cli.main(['collect']), 1)
        store.assert_not_called()
        self.assertIn('config.ini', '\n'.join(captured.output))

    def test_R4_invalid_daily_limit_does_not_block_collect(self):
        config = Config(CONFIG.db, CONFIG.arxiv, TelegramConfig(TOKEN, '42', 'abc'))
        p1 = self.papers[0]
        code, _ = self.main_collect(UpdateBot([click(1, p1, 1, 101)]), config)
        self.assertEqual(code, 0)
        self.assertEqual(self.feedback(), {p1: 1})

    # ---------------- R5 ----------------

    def status_text(self):
        output = io.StringIO()
        with patch.object(cli, 'Store', return_value=self.store), redirect_stdout(output):
            self.assertEqual(cli.cmd_status(Namespace(limit=10), CONFIG), 0)
        return output.getvalue()

    def test_R5_status_summary(self):
        more = [self.store.add_paper(n, NOW) for n in range(10, 17)]
        for paper_id in more:
            self.store.db.connection.execute(
                'INSERT INTO pushes (batch_id, paper_id, chat_id, message_id) VALUES (1,?,?,?)', (paper_id, '42', 100 + paper_id))
        for paper_id, label in zip(self.papers + more[:1], (0, 1, 1, 2)):
            self.store.save_feedback(paper_id, label)
        text = self.status_text()
        for part in ('推送 10 篇', '回饋 4 篇', '40%', '👎 1', '👍 2', '⭐ 1'):
            self.assertIn(part, text)

    def test_R5_status_without_pushes(self):
        self.store.db.connection.execute('DELETE FROM pushes')
        text = self.status_text()
        self.assertIn('推送 0 篇', text)
        self.assertIn('回饋 0 篇', text)

    # ---------------- D1 ----------------

    def test_D1_registered_and_offline(self):
        config = json.loads(Path('workflow.config.json').read_text(encoding='utf-8'))
        self.assertIn('tests/test_feedback_collect.py', config['testFiles'])
        self.collect(UpdateBot([click(1, self.papers[0], 1, 101)]))
        self.main_collect(UpdateBot([], fail_get=True))
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
