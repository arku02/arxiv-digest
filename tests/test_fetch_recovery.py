"""Offline acceptance tests for fetch failure handling: rate-limit wait, failure notice, push hold and hourly catch-up."""
from datetime import datetime, timedelta
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from arxiv_digest import cli
from arxiv_digest.config import ArxivConfig, Config, RetryConfig, TelegramConfig, load_config
from arxiv_digest.fetcher import ArxivFetcher
from arxiv_digest.notifier import TelegramClient

# Share the SQLite store double without importing the other test module's TestCase.
_spec = importlib.util.spec_from_file_location('_push_helpers', Path(__file__).with_name('test_telegram_push.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)

TOKEN, NOW = helpers.TOKEN, helpers.NOW
ARXIV = ArxivConfig(['cs.CL'], 10, 50, 0, 1)
CONFIG = Config(helpers.CONFIG.db, ARXIV, helpers.TELEGRAM)
PLACEHOLDER = Config(CONFIG.db, ARXIV, helpers.PLACEHOLDER.telegram)
START, END = datetime(2026, 9, 1), datetime(2026, 9, 2)
MORNING = datetime(2026, 9, 28, 11, 0)
LIMIT_ERROR = '已達單次上限 50 筆，區間尚未抓完；本批次未寫入，續抓起點保留。'


def feed(numbers):
    entries = ''.join(f'''<entry><id>http://arxiv.org/abs/2609.{n:05}v1</id>
        <title>Fetched {n}</title><summary>Offline sample</summary>
        <published>2026-09-27T00:00:00Z</published><updated>2026-09-27T00:00:00Z</updated>
        <category term="cs.CL"/><author><name>Example</name></author></entry>'''
        for n in numbers)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'


class ArxivResponse:
    def __init__(self, status, text='', headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class ArxivSession:
    """Simulated arXiv API. script lists status codes (or (status, headers)); the last one repeats."""
    def __init__(self, script=(200,), total=0):
        self.script, self.total, self.calls = list(script), total, []

    def get(self, url, params, timeout):
        self.calls.append(params)
        step = self.script[min(len(self.calls), len(self.script)) - 1]
        status, headers = step if isinstance(step, tuple) else (step, {})
        if status != 200:
            return ArxivResponse(status, headers=headers)
        start, size = params['start'], params['max_results']
        # Paper numbers start at 900 so they never collide with seeded papers.
        return ArxivResponse(200, feed(range(900 + start, 900 + min(start + size, self.total))))


class Bot:
    """Simulated Bot API: getUpdates (empty queue) and sendMessage."""
    def __init__(self, *, fail_send=False, fail_updates=False):
        self.calls, self.fail_send, self.fail_updates = [], fail_send, fail_updates

    def post(self, url, json, timeout):
        method = url.rsplit('/', 1)[1]
        self.calls.append((method, json))
        if method == 'getUpdates':
            if self.fail_updates:
                raise requests.ConnectionError('getUpdates unavailable')
            return helpers.Response(200, {'ok': True, 'result': []})
        if method == 'sendMessage':
            if self.fail_send:
                raise requests.ConnectionError(f'HTTPSConnectionPool: Max retries exceeded with url: /bot{TOKEN}/sendMessage')
            return helpers.Response(200, {'ok': True, 'result': {'message_id': 500 + len(self.calls)}})
        raise AssertionError('Unexpected Bot API method ' + method)

    def method_calls(self, method):
        return [payload for name, payload in self.calls if name == method]


def with_retry(enabled='true', start='10', end='22', config=CONFIG):
    return Config(config.db, config.arxiv, config.telegram, config.translate, RetryConfig(enabled, start, end))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

    # ---------------- helpers ----------------

    def store(self, *runs):
        """SQLite store with a successful push batch a day ago and 3 unpushed papers after it."""
        store = helpers.SQLiteStore()
        t0 = NOW - timedelta(days=1)
        store.add_batch(t0, 'success')
        self.pool = [store.add_paper(n, t0 + timedelta(hours=n)) for n in range(1, 4)]
        for run in runs:
            self.add_run(store, *run)
        return store

    @staticmethod
    def add_run(store, status, error=None, started=NOW - timedelta(hours=3)):
        end = started - timedelta(hours=8)
        store.db.connection.execute(
            'INSERT INTO runs (window_start, window_end, started_at, status, error) VALUES (?,?,?,?,?)',
            ((end - timedelta(days=1)).isoformat(' '), end.isoformat(' '), started.isoformat(' '), status, error))

    @staticmethod
    def runs(store):
        return store.rows('SELECT status, error FROM runs ORDER BY id')

    @staticmethod
    def batches(store):
        return store.rows('SELECT status, sent FROM push_batches ORDER BY id')

    def run_cli(self, argv, store, *, config=CONFIG, arxiv=None, bot=None, local=MORNING):
        arxiv = arxiv or ArxivSession()
        bot = bot or Bot()
        waits = []
        with patch.object(cli, 'load_config', return_value=config), patch.object(cli, 'Store', return_value=store), \
                patch.object(cli, 'ArxivFetcher', side_effect=lambda c: ArxivFetcher(c, session=arxiv)), \
                patch.object(cli, 'TelegramClient', side_effect=lambda token, chat_id: TelegramClient(token, chat_id, session=bot)), \
                patch.object(cli, 'utcnow', return_value=NOW), patch.object(cli, 'localnow', return_value=local), \
                patch('time.sleep', side_effect=waits.append):
            with self.assertLogs('arxiv_digest', level='INFO') as captured:
                code = cli.main(list(argv))
        return code, '\n'.join(captured.output), arxiv, bot

    @staticmethod
    def fetch_waits(script, delay=0):
        fetcher = ArxivFetcher(ArxivConfig(['cs.CL'], 10, 50, delay, 1), session=ArxivSession(script))
        with patch('time.sleep') as sleep, patch('time.monotonic', side_effect=itertools.count(1000, 1000)):
            try:
                result = fetcher.fetch(START, END)
            except RuntimeError as exc:
                result = exc
        return result, [call.args[0] for call in sleep.call_args_list]

    # ---------------- R6 ----------------

    def test_R6_retry_after_is_honored_and_capped(self):
        self.assertEqual(self.fetch_waits([(429, {'Retry-After': '30'}), 200]), ([], [30]))
        self.assertEqual(self.fetch_waits([(503, {'Retry-After': '9999'}), 200]), ([], [300]))

    def test_R6_default_rate_limit_backoff(self):
        self.assertEqual(self.fetch_waits([429, (503, {'Retry-After': 'soon'}), 200]), ([], [60, 120]))

    def test_R6_persistent_rate_limit_fails_without_final_wait(self):
        error, waits = self.fetch_waits([429])
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('HTTP 429', str(error))
        self.assertEqual(waits, [60, 120])

    def test_R6_other_errors_keep_request_delay(self):
        self.assertEqual(self.fetch_waits([500, 200], delay=3), ([], [3]))
        self.assertEqual(self.fetch_waits([500], delay=3)[1], [3, 6])

    # ---------------- R7 ----------------

    def test_R7_first_failure_notifies_once(self):
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, arxiv=ArxivSession([429]))
        self.assertEqual(code, 1)
        self.assertEqual(self.runs(store)[-1]['status'], 'failed')
        self.assertEqual(len(bot.method_calls('sendMessage')), 1)
        notice = bot.method_calls('sendMessage')[0]
        self.assertNotIn('reply_markup', notice)
        self.assertEqual(notice['parse_mode'], 'HTML')
        for text in ('HTTP 429', '10:00', '22:00', '不推送'):
            self.assertIn(text, notice['text'])

    def test_R7_consecutive_failure_is_silent(self):
        store = self.store(('success',), ('failed', 'arXiv API 連續 3 次請求失敗：HTTP 429'))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, arxiv=ArxivSession([429]))
        self.assertEqual(code, 1)
        self.assertEqual(bot.calls, [])

    def test_R7_limit_failure_needs_operator(self):
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, arxiv=ArxivSession([200], total=80))
        self.assertEqual(code, 1)
        text = bot.method_calls('sendMessage')[0]['text']
        self.assertIn('max_results', text)
        self.assertIn('不會自動重試', text)

    def test_R7_retry_disabled_asks_for_manual_rerun(self):
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, config=with_retry('false'), arxiv=ArxivSession([429]))
        self.assertEqual(code, 1)
        self.assertIn('手動', bot.method_calls('sendMessage')[0]['text'])

    def test_R7_telegram_unavailable_keeps_failure(self):
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, config=PLACEHOLDER, arxiv=ArxivSession([429]))
        self.assertEqual((code, bot.calls), (1, []))
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, arxiv=ArxivSession([429]), bot=Bot(fail_send=True))
        self.assertEqual(code, 1)
        self.assertEqual(self.runs(store)[-1]['status'], 'failed')
        self.assertNotIn(TOKEN, logs)
        self.assertIn('<bot_token>', logs)

    # ---------------- R8 ----------------

    def test_R8_retry_succeeds_and_pushes(self):
        store = self.store(('success',), ('failed', 'arXiv API 連續 3 次請求失敗：HTTP 429'))
        code, logs, arxiv, bot = self.run_cli(['collect'], store)
        self.assertEqual(code, 0)
        self.assertEqual(len(bot.method_calls('getUpdates')), 1)
        self.assertEqual(self.runs(store)[-1]['status'], 'success')
        sent = bot.method_calls('sendMessage')
        self.assertEqual(len(sent), 3)
        self.assertTrue(all('reply_markup' in payload for payload in sent))
        self.assertEqual(sorted(store.pushed_ids()), self.pool)
        self.assertEqual(self.batches(store)[-1], {'status': 'success', 'sent': 3})

    def test_R8_retry_runs_even_when_feedback_fails(self):
        store = self.store(('success',), ('failed', 'HTTP 429'))
        code, logs, arxiv, bot = self.run_cli(['collect'], store, bot=Bot(fail_updates=True))
        self.assertEqual(code, 1)
        self.assertEqual(self.runs(store)[-1]['status'], 'success')
        self.assertEqual(len(bot.method_calls('sendMessage')), 3)

    def test_R8_retry_fails_again_without_new_notice(self):
        store = self.store(('success',), ('failed', 'arXiv API 連續 3 次請求失敗：HTTP 429'))
        code, logs, arxiv, bot = self.run_cli(['collect'], store, arxiv=ArxivSession([429]))
        self.assertEqual(code, 1)
        self.assertEqual([r['status'] for r in self.runs(store)], ['success', 'failed', 'failed'])
        self.assertEqual(bot.method_calls('sendMessage'), [])
        self.assertEqual(len(self.batches(store)), 1)

    def test_R8_outside_retry_hours(self):
        for hour in (9, 22, 23, 3):
            with self.subTest(hour=hour):
                store = self.store(('failed', 'HTTP 429'))
                code, logs, arxiv, bot = self.run_cli(['collect'], store, local=datetime(2026, 9, 28, hour, 0))
                self.assertEqual((code, arxiv.calls, bot.method_calls('sendMessage')), (0, [], []))

    def test_R8_nothing_to_retry(self):
        cases = {'success': ('success',), 'limit': ('failed', LIMIT_ERROR),
                 'running': ('running', None, NOW - timedelta(minutes=10))}
        for name, run in cases.items():
            with self.subTest(name):
                store = self.store(run)
                code, logs, arxiv, bot = self.run_cli(['collect'], store)
                self.assertEqual((code, arxiv.calls, bot.method_calls('sendMessage')), (0, [], []))

    def test_R8_stale_running_is_retried(self):
        store = self.store(('success',), ('running', None, NOW - timedelta(minutes=90)))
        code, logs, arxiv, bot = self.run_cli(['collect'], store)
        self.assertEqual(code, 0)
        self.assertTrue(arxiv.calls)
        self.assertEqual(len(bot.method_calls('sendMessage')), 3)

    def test_R8_invalid_settings_block_retry_only(self):
        for config, name in ((with_retry(start='22', end='10'), 'start_hour'), (with_retry('maybe'), 'enabled'),
                             (with_retry(end='25'), 'end_hour')):
            with self.subTest(name):
                store = self.store(('failed', 'HTTP 429'))
                code, logs, arxiv, bot = self.run_cli(['collect'], store, config=config)
                self.assertEqual((code, arxiv.calls), (1, []))
                self.assertIn(name, logs)
                self.assertEqual(len(bot.method_calls('getUpdates')), 1)
        store = self.store(('success',))
        code, logs, arxiv, bot = self.run_cli(['daily'], store, config=with_retry(start='22', end='10'))
        self.assertEqual(code, 0)

    def test_R8_settings_from_config_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.ini'
            path.write_text(helpers.INI, encoding='utf-8')
            self.assertEqual(load_config(path).retry.validated(), (10, 22))
            path.write_text(helpers.INI + '[RETRY]\nenabled = false\n', encoding='utf-8')
            self.assertIsNone(load_config(path).retry.validated())
            path.write_text(helpers.INI + '[RETRY]\nstart_hour = 8\nend_hour = 20\n', encoding='utf-8')
            self.assertEqual(load_config(path).retry.validated(), (8, 20))

    # ---------------- R10 ----------------

    def test_R10_push_held_after_failed_fetch(self):
        for status in ('failed', 'running'):
            with self.subTest(status):
                store = self.store(('success',), (status, 'HTTP 429' if status == 'failed' else None))
                code, logs, arxiv, bot = self.run_cli(['push'], store)
                self.assertEqual((code, bot.calls), (1, []))
                self.assertEqual(len(self.batches(store)), 1)
                self.assertIn('抓取', logs)

    def test_R10_push_resumes_after_recovery(self):
        store = self.store(('failed', 'HTTP 429'))
        self.assertEqual(self.run_cli(['push'], store)[0], 1)
        self.add_run(store, 'success', started=NOW - timedelta(minutes=5))
        code, logs, arxiv, bot = self.run_cli(['push'], store)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(store.pushed_ids()), self.pool)

    def test_R10_preview_still_works(self):
        store = self.store(('failed', 'HTTP 429'))
        with patch('sys.stdout'):
            code, logs, arxiv, bot = self.run_cli(['push', '--dry-run'], store, config=PLACEHOLDER)
        self.assertEqual((code, bot.calls), (0, []))
        self.assertIn('WARNING', logs)
        self.assertEqual(len(self.batches(store)), 1)

    # ---------------- D1 ----------------

    def test_D1_registered_and_offline(self):
        config = json.loads(Path('workflow.config.json').read_text(encoding='utf-8'))
        self.assertIn('tests/test_fetch_recovery.py', config['testFiles'])
        store = self.store(('success',), ('failed', 'HTTP 429'))
        self.run_cli(['collect'], store)
        self.run_cli(['daily'], self.store(('success',)), arxiv=ArxivSession([429]))
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
