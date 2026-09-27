"""Offline acceptance tests: real fetch/CLI logic, simulated API and SQL store."""
from argparse import Namespace
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from arxiv_digest.config import ArxivConfig, Config, DBConfig, load_config
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


# Announcement-lag scenario: submitted Friday after the cutoff, searchable only
# after the Monday evening (ET) announcement plus index delay.
LAST_SUCCESS = datetime(2026, 9, 18, 2, 12)
FRIDAY_PAPER = datetime(2026, 9, 18, 19, 0)
MONDAY_PAPER = datetime(2026, 9, 21, 15, 0)
MONDAY_VISIBLE = datetime(2026, 9, 22, 1, 30)
DAILY_RUNS = [datetime(2026, 9, 19, 8, 0), datetime(2026, 9, 20, 8, 10),
              datetime(2026, 9, 21, 8, 0), datetime(2026, 9, 22, 9, 11)]
LAG_CONFIG = replace(CONFIG, arxiv=replace(CONFIG.arxiv, page_size=10, max_results=50))
INI = '''[DB]
host = localhost
user = test
password = unused
port = 3306
database = offline
[ARXIV]
categories = cs.CL
'''


def paper_id(number):
    return f'2609.{number:05}'


class ArchiveSession:
    """Simulated API: a paper is searchable only once its visible time has passed."""
    def __init__(self, papers):
        self.papers, self.now, self.windows = papers, None, []

    def get(self, url, params, timeout):
        low, high = (datetime.strptime(value, '%Y%m%d%H%M') for value in
                     re.search(r'\[(\d{12}) TO (\d{12})\]', params['search_query']).groups())
        self.windows.append((low, high))
        found = sorted((submitted, n) for n, submitted, visible in self.papers
                       if low <= submitted <= high and visible <= self.now)
        page = found[params['start']:params['start'] + params['max_results']]
        entries = ''.join(f'''<entry><id>http://arxiv.org/abs/{paper_id(n)}v1</id>
            <title>Paper {n}</title><summary>Offline sample</summary>
            <published>{submitted:%Y-%m-%dT%H:%M:%SZ}</published><updated>{submitted:%Y-%m-%dT%H:%M:%SZ}</updated>
            <category term="cs.CL"/><author><name>Example</name></author></entry>'''
            for submitted, n in page)
        text = f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
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

    def next_fetch_start(self, *args):
        return self.real.next_fetch_start(*args)

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

    def seed_success(self, since, until):
        # Keep records and SQL ids aligned for tests that later call run_fetch.
        self.finish_run(self.start_run(since, until), 'success')


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

    def run_job(self, store, count, *, config=CONFIG, now=END, since=None, fail_probe=False, session=None):
        session = session or Session(count, fail_probe)
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

    def test_R3_repeated_failures_keep_same_start(self):
        store = MemoryStore()
        store.seed_success(START - timedelta(days=1), START)
        for day in (1, 2):
            with self.assertRaises(RuntimeError):
                self.run_job(store, 5, now=START + timedelta(days=day))
        self.assertEqual(self.run_job(store, 3, now=START + timedelta(days=3))[0], 3)
        expected = START - timedelta(days=4)
        self.assertEqual([r['start'] for r in store.records[1:]], [expected] * 3)
        self.assertEqual([r['status'] for r in store.records[1:]], ['failed', 'failed', 'success'])

    def run_lag_week(self, config=LAG_CONFIG):
        store = MemoryStore()
        store.seed_success(LAST_SUCCESS - timedelta(days=1), LAST_SUCCESS)
        session = ArchiveSession([(1, FRIDAY_PAPER, MONDAY_VISIBLE), (2, MONDAY_PAPER, MONDAY_VISIBLE)])
        for now in DAILY_RUNS:
            session.now = now
            self.run_job(store, 0, config=config, now=now, session=session)
        return store, session

    def test_R5_paper_announced_after_earlier_runs_is_saved(self):
        store, _ = self.run_lag_week()
        self.assertEqual([r['new_count'] for r in store.records[1:]], [0, 0, 0, 2])
        self.assertEqual(store.papers, {paper_id(1), paper_id(2)})
        self.assertEqual(store.records[-1]['start'], DAILY_RUNS[2] - timedelta(days=4))

    def test_R5_lookback_zero_misses_announced_paper(self):
        disabled = replace(LAG_CONFIG, arxiv=replace(LAG_CONFIG.arxiv, lookback_days=0))
        store, _ = self.run_lag_week(disabled)
        self.assertEqual(store.papers, {paper_id(2)})
        self.assertEqual(store.records[-1]['start'], DAILY_RUNS[2])

    def test_R5_overlap_is_deduplicated(self):
        store = MemoryStore()
        store.seed_success(LAST_SUCCESS - timedelta(days=1), LAST_SUCCESS)
        early = datetime(2026, 9, 20, 10, 0)
        session = ArchiveSession([(1, early, early + timedelta(hours=2)), (2, MONDAY_PAPER, MONDAY_VISIBLE)])
        for now in (datetime(2026, 9, 21, 8, 0), datetime(2026, 9, 22, 8, 0)):
            session.now = now
            self.run_job(store, 0, config=LAG_CONFIG, now=now, session=session)
        self.assertEqual(store.records[-1]['fetched'], 2)
        self.assertEqual(store.records[-1]['new_count'], 1)
        self.assertEqual(store.papers, {paper_id(1), paper_id(2)})

    def test_R5_default_and_zero_lookback_from_config_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.ini'
            path.write_text(INI, encoding='utf-8')
            self.assertEqual(load_config(path).arxiv.lookback_days, 4)
            path.write_text(INI + 'lookback_days = 0\n', encoding='utf-8')
            self.assertEqual(load_config(path).arxiv.lookback_days, 0)

    def test_R5_invalid_lookback_rejected_before_connection(self):
        for value in (-1, 1.5, True, '4'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(CONFIG.arxiv, lookback_days=value)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.ini'
            for value in ('-1', 'abc'):
                with self.subTest(value=value):
                    path.write_text(INI + f'lookback_days = {value}\n', encoding='utf-8')
                    with patch.object(cli, 'Store', side_effect=AssertionError('DB opened')) as store, \
                            patch.object(cli, 'ArxivFetcher', side_effect=AssertionError('fetcher built')) as fetcher:
                        self.assertEqual(cli.main(['--config', str(path), 'daily']), 1)
                    store.assert_not_called()
                    fetcher.assert_not_called()

    def test_R5_backfill_keeps_explicit_start(self):
        store = MemoryStore()
        store.seed_success(START - timedelta(days=1), START)
        now = END + timedelta(days=3)
        factory = lambda c: ArxivFetcher(c, session=Session(3))
        with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'ArxivFetcher', side_effect=factory), patch.object(cli, 'utcnow', return_value=now):
            self.assertEqual(cli.cmd_backfill(Namespace(days=7), CONFIG), 0)
        self.assertEqual(store.records[-1]['start'], now - timedelta(days=7))

    def test_D1_lookback_scenarios_stay_offline(self):
        self.run_lag_week()
        self.test_R5_invalid_lookback_rejected_before_connection()
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
