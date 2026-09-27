"""Offline acceptance tests: real fetch/CLI logic, simulated API and SQL store."""
from dataclasses import replace
from datetime import datetime, timedelta
import sqlite3
import unittest
from unittest.mock import patch

from arxiv_digest.config import ArxivConfig, Config, DBConfig
from arxiv_digest.fetcher import ArxivFetcher
from arxiv_digest import cli
from arxiv_digest.store import Store


START = datetime(2026, 9, 1)
END = datetime(2026, 9, 2)
CONFIG = Config(DBConfig('invalid', 'test', 'unused', 3306, 'offline'),
                ArxivConfig(['cs.CL'], 2, 4, 0, 1))


def atom(numbers):
    entries = ''.join(f'''<entry><id>http://arxiv.org/abs/2609.{n:05}v1</id>
        <title>Paper {n}</title><summary>Offline sample</summary>
        <published>2026-09-01T00:00:00Z</published><updated>2026-09-01T00:00:00Z</updated>
        <category term="cs.CL"/><author><name>Example</name></author></entry>'''
        for n in numbers)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'


class Session:
    def __init__(self, count, fail_probe=False):
        self.count, self.fail_probe, self.calls = count, fail_probe, []

    def get(self, url, params, timeout):
        start, size = params['start'], params['max_results']
        self.calls.append((start, size))
        if self.fail_probe and start == CONFIG.arxiv.max_results:
            raise RuntimeError('probe unavailable')
        text = atom(range(start + 1, min(start + size, self.count) + 1))
        return type('Response', (), {'status_code': 200, 'text': text})()


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, args=()):
        self.cursor.execute(sql.replace('%s', '?'), args)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {k: datetime.fromisoformat(v) if v and k in ('window_start', 'window_end') else v
                for k, v in dict(row).items()}


class SQLConnection:
    """Execute actual read queries on SQLite; this does not certify MySQL integration."""
    def __init__(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('CREATE TABLE runs (id INTEGER PRIMARY KEY, window_start TEXT, window_end TEXT, status TEXT)')

    def cursor(self):
        return Cursor(self.connection)

    def add(self, start, end, status):
        self.connection.execute('INSERT INTO runs(window_start,window_end,status) VALUES (?,?,?)',
                                (start.isoformat(' '), end.isoformat(' '), status))


class MemoryStore:
    def __init__(self):
        self.sql = SQLConnection()
        self.real = Store(CONFIG.db)
        self.real.db = self.sql
        self.records, self.papers = [], set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def init_schema(self):
        pass

    def last_success_window_end(self):
        return self.real.last_success_window_end()

    def next_fetch_start(self):
        return self.real.next_fetch_start()

    def start_run(self, since, until):
        self.records.append({'start': since, 'end': until, 'status': 'running'})
        self.sql.add(since, until, 'running')
        return len(self.records)

    def finish_run(self, run_id, status, **kwargs):
        self.records[run_id - 1].update(status=status, **kwargs)
        self.sql.connection.execute('UPDATE runs SET status=? WHERE id=?', (status, run_id))

    def save_papers(self, papers):
        before = len(self.papers)
        self.papers.update(p.arxiv_id for p in papers)
        new = len(self.papers) - before
        return new, len(papers) - new

    def count_papers(self):
        return len(self.papers)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.network.start()
        self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

    def run_job(self, store, count, *, config=CONFIG, now=END, since=None, fail_probe=False):
        session = Session(count, fail_probe)
        factory = lambda c: ArxivFetcher(c, session=session)
        with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'ArxivFetcher', side_effect=factory), patch.object(cli, 'utcnow', return_value=now):
            return cli.run_fetch(config, since), session

    def test_R1_under_limit_is_success(self):
        store = MemoryStore()
        result, session = self.run_job(store, 3)
        self.assertEqual(result, 3)
        self.assertEqual(session.calls, [(0, 2), (2, 2)])
        self.assertEqual(store.last_success_window_end(), END)

    def test_R1_no_results_is_success(self):
        store = MemoryStore()
        self.assertEqual(self.run_job(store, 0)[0], 0)
        self.assertEqual(store.records[-1]['status'], 'success')

    def test_R1_empty_time_range_makes_no_request(self):
        session = Session(9)
        self.assertEqual(ArxivFetcher(CONFIG.arxiv, session).fetch(END, START), [])
        self.assertEqual(session.calls, [])

    def test_R2_exact_limit_probes_and_completes(self):
        store = MemoryStore()
        result, session = self.run_job(store, 4)
        self.assertEqual(result, 4)
        self.assertEqual(session.calls, [(0, 2), (2, 2), (4, 1)])
        self.assertEqual(store.records[-1]['status'], 'success')

    def test_R2_over_limit_is_not_success_and_does_not_save_partial_batch(self):
        store = MemoryStore()
        with self.assertRaisesRegex(RuntimeError, '上限'):
            self.run_job(store, 5)
        self.assertEqual(store.records[-1]['status'], 'failed')
        self.assertIsNone(store.last_success_window_end())
        self.assertEqual(store.papers, set())

    def test_R2_probe_failure_is_not_success(self):
        store = MemoryStore()
        with self.assertRaisesRegex(RuntimeError, 'probe unavailable'):
            self.run_job(store, 4, fail_probe=True)
        self.assertEqual(store.records[-1]['status'], 'failed')
        self.assertEqual(store.papers, set())

    def test_R2_invalid_limits_fail_before_http(self):
        for field in ('page_size', 'max_results'):
            for value in (0, -1):
                with self.subTest(field=field, value=value):
                    session = Session(3)
                    with self.assertRaises(ValueError):
                        ArxivFetcher(replace(CONFIG.arxiv, **{field: value}), session).fetch(START, END)
                    self.assertEqual(session.calls, [])

    def test_R3_first_failed_attempt_keeps_start_on_later_day(self):
        store = MemoryStore()
        try:
            self.run_job(store, 5)
        except RuntimeError:
            pass
        expanded = replace(CONFIG, arxiv=replace(CONFIG.arxiv, max_results=6))
        self.assertEqual(self.run_job(store, 5, config=expanded, now=END + timedelta(days=1))[0], 5)
        self.assertEqual(store.records[-1]['start'], START)
        self.assertEqual(store.records[-1]['status'], 'success')
        self.assertEqual(store.next_fetch_start(), END + timedelta(days=1))

    def test_R3_retry_from_previous_success_keeps_window(self):
        store = MemoryStore()
        previous = START - timedelta(days=1)
        store.sql.add(previous, START, 'success')
        # No new run is needed here: query semantics are tested on actual stored rows.
        store.sql.add(START, END, 'failed')
        self.assertEqual(store.next_fetch_start(), START)

    def test_R3_running_attempt_is_retried(self):
        store = MemoryStore()
        store.sql.add(START, END, 'running')
        self.assertEqual(store.next_fetch_start(), START)

    def test_R3_older_failed_backfill_is_not_hidden_by_recent_success(self):
        store = MemoryStore()
        store.sql.add(START, END, 'failed')
        store.sql.add(END, END + timedelta(days=1), 'success')
        self.assertEqual(store.next_fetch_start(), START)

    def test_R3_covered_failure_is_retired(self):
        store = MemoryStore()
        store.sql.add(START, END, 'failed')
        store.sql.add(START, END + timedelta(days=1), 'success')
        self.assertEqual(store.next_fetch_start(), END + timedelta(days=1))

    def test_R3_repeated_complete_fetch_remains_deduplicated(self):
        store = MemoryStore()
        self.assertEqual(self.run_job(store, 3, since=START)[0], 3)
        self.assertEqual(self.run_job(store, 3, since=START)[0], 0)
        self.assertEqual(len(store.papers), 3)

    def test_R4_cli_returns_failure_with_actionable_message(self):
        store = MemoryStore()
        with patch.object(cli, 'load_config', return_value=CONFIG), patch.object(cli, 'Store', return_value=store), patch.object(cli, 'utcnow', return_value=END), patch.object(cli, 'ArxivFetcher', side_effect=lambda c: ArxivFetcher(c, Session(5))):
            with self.assertLogs('arxiv_digest', level='ERROR') as captured:
                code = cli.main(['daily'])
        self.assertEqual(code, 1)
        text = '\n'.join(captured.output)
        self.assertIn('max_results', text)
        self.assertIn('重跑', text)
        self.assertIn('起點', text)
        self.assertIn('UTC 2026-09-01 00:00 ~ 2026-09-02 00:00', text)
        self.assertIn('不會自動調高上限', text)


if __name__ == '__main__':
    unittest.main()
