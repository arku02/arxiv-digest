"""Offline acceptance tests for push translation: real CLI/Store logic, SQLite, simulated Ollama and Bot API."""
from contextlib import redirect_stdout
from datetime import timedelta
import importlib.util
import io
import json as jsonlib
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import requests

from arxiv_digest import cli
from arxiv_digest.config import Config, TelegramConfig, TranslateConfig, load_config
from arxiv_digest.notifier import PushPaper, TelegramClient, format_message
from arxiv_digest.translator import OllamaTranslator, Translation

# Share the SQLite store double without importing the other test module's TestCase.
_spec = importlib.util.spec_from_file_location('_push_helpers', Path(__file__).with_name('test_telegram_push.py'))
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)

NOW = helpers.NOW
ENABLED = Config(helpers.CONFIG.db, helpers.CONFIG.arxiv, helpers.TELEGRAM, TranslateConfig('true'))
DISABLED = Config(helpers.CONFIG.db, helpers.CONFIG.arxiv, helpers.TELEGRAM, TranslateConfig('false'))
PREVIEW = Config(helpers.CONFIG.db, helpers.CONFIG.arxiv,
                 TelegramConfig('YOUR_BOT_TOKEN_HERE', 'YOUR_CHAT_ID_HERE', '10'), TranslateConfig('true'))


class OllamaSession:
    """Simulated Ollama /api/chat; translates by prefixing the English title."""
    def __init__(self, fail_at=None, invalid_at=None, invalid_content='not json', status=200):
        self.calls, self.fail_at, self.invalid_at = [], fail_at, invalid_at
        self.invalid_content, self.status = invalid_content, status

    def post(self, url, json, timeout):
        index = len(self.calls)
        self.calls.append((url, json, timeout))
        if self.fail_at == index:
            raise requests.ConnectionError('Max retries exceeded: connection refused')
        if self.status != 200:
            return helpers.Response(self.status, {'error': 'model runner crashed'})
        if self.invalid_at == index:
            return helpers.Response(200, {'message': {'content': self.invalid_content}})
        title = json['messages'][-1]['content'].split('\n')[0].removeprefix('標題：')
        content = jsonlib.dumps({'title_zh': f'中文：{title}', 'summary_zh': f'中文摘要：{title}'}, ensure_ascii=False)
        return helpers.Response(200, {'message': {'content': content}})


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden'))
        self.database = patch('pymysql.connect', side_effect=AssertionError('Live DB forbidden'))
        self.http = self.network.start()
        self.db = self.database.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.database.stop)

    def store_with(self, count):
        store = helpers.SQLiteStore()
        for n in range(1, count + 1):
            store.add_paper(n, NOW - timedelta(minutes=n), summary=f'English   abstract\n of paper {n}.')
        return store

    def push(self, store, ollama, config=ENABLED, dry_run=False, bot=None):
        bot = bot or helpers.BotSession()
        telegram = lambda token, chat_id: TelegramClient(token, chat_id, session=bot)
        translator = lambda model, url, timeout: OllamaTranslator(model, url, timeout, session=ollama)
        with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'TelegramClient', side_effect=telegram), \
                patch.object(cli, 'OllamaTranslator', side_effect=translator):
            sent = cli.run_push(config, dry_run=dry_run, rng=random.Random(7), sleep=lambda s: None)
        return sent, bot

    @staticmethod
    def texts(bot):
        return [payload['text'] for _, payload in bot.calls]

    # ---------------- R2 ----------------

    def test_R2_translated_message_format(self):
        paper = PushPaper(id=7, arxiv_id='2609.00007', title='Original <Title>', summary='English abstract ' * 30,
                          categories='cs.AI,cs.CL', authors=['A1', 'A2', 'A3', 'A4', 'A5'])
        text = format_message(paper, Translation('中文 <標題> & 測試', '這是  中文摘要。'))
        self.assertEqual(text.split('\n')[:4], ['<b>中文 &lt;標題&gt; &amp; 測試</b>', 'Original &lt;Title&gt;',
                                                'A1, A2, A3 等 5 人', '<i>cs.AI, cs.CL</i>'])
        self.assertIn('\n\n這是 中文摘要。\n\n', text)
        self.assertNotIn('English abstract', text)
        self.assertTrue(text.endswith('<a href="https://arxiv.org/abs/2609.00007">arXiv:2609.00007</a>'))

    def test_R2_long_translation_is_clipped(self):
        paper = PushPaper(id=1, arxiv_id='2609.00001', title='T', summary='S', categories='cs.AI')
        text = format_message(paper, Translation('標題', '字' * 2000))
        self.assertIn('字' * 1500 + '…', text)
        self.assertNotIn('字' * 1501, text)
        self.assertLess(len(text), 4096)

    def test_R2_untranslated_format_unchanged(self):
        paper = PushPaper(id=1, arxiv_id='2609.00001', title='Title', summary='word ' * 100, categories='cs.AI')
        self.assertEqual(format_message(paper), format_message(paper, None))
        self.assertTrue(format_message(paper).startswith('<b>Title</b>\n'))
        self.assertIn('…', format_message(paper))

    # ---------------- R6 ----------------

    def test_R6_push_translates_each_paper_once(self):
        store = self.store_with(3)
        ollama = OllamaSession()
        sent, bot = self.push(store, ollama)
        self.assertEqual(sent, 3)
        self.assertEqual(len(ollama.calls), 3)
        url, payload, timeout = ollama.calls[0]
        self.assertEqual(url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(timeout, 300.0)
        self.assertEqual((payload['model'], payload['stream'], payload['think']), ('qwen3.5:9b', False, False))
        self.assertEqual(payload['format']['required'], ['title_zh', 'summary_zh'])
        self.assertEqual(payload['messages'][0]['role'], 'system')
        self.assertIn('繁體中文', payload['messages'][0]['content'])
        user = [p['messages'][-1]['content'] for _, p, _ in ollama.calls]
        for n in range(1, 4):
            self.assertIn(f'標題：Paper {n}\n\n摘要：English abstract of paper {n}.', user)
        for text in self.texts(bot):
            self.assertTrue(text.startswith('<b>中文：Paper '))
            self.assertIn('中文摘要：Paper ', text)

    def test_R6_dry_run_translates_without_telegram(self):
        store = self.store_with(2)
        ollama = OllamaSession()
        output = io.StringIO()
        translator = lambda model, url, timeout: OllamaTranslator(model, url, timeout, session=ollama)
        with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'OllamaTranslator', side_effect=translator), \
                patch.object(cli, 'TelegramClient', side_effect=AssertionError('Telegram used')), redirect_stdout(output):
            self.assertEqual(cli.run_push(PREVIEW, dry_run=True, rng=random.Random(7), sleep=lambda s: None), 0)
        self.assertEqual(len(ollama.calls), 2)
        self.assertIn('<b>中文：Paper 1</b>', output.getvalue())
        self.assertEqual(store.rows('SELECT * FROM pushes'), [])

    # ---------------- R7 ----------------

    def test_R7_ollama_down_falls_back_after_one_request(self):
        store = self.store_with(10)
        ollama = OllamaSession(fail_at=0)
        with self.assertLogs('arxiv_digest', level='WARNING') as captured:
            sent, bot = self.push(store, ollama)
        self.assertEqual(sent, 10)
        self.assertEqual(len(ollama.calls), 1)
        self.assertTrue(all(text.startswith('<b>Paper ') for text in self.texts(bot)))
        self.assertEqual(store.rows('SELECT status, sent FROM push_batches'), [{'status': 'success', 'sent': 10}])
        self.assertIn('翻譯', '\n'.join(captured.output))

    def test_R7_invalid_output_mid_batch(self):
        store = self.store_with(4)
        ollama = OllamaSession(invalid_at=1)
        with self.assertLogs('arxiv_digest', level='WARNING'):
            _, bot = self.push(store, ollama)
        texts = self.texts(bot)
        self.assertEqual(len(ollama.calls), 2)
        self.assertTrue(texts[0].startswith('<b>中文：'))
        self.assertTrue(all(text.startswith('<b>Paper ') for text in texts[1:]))

    def test_R7_empty_fields_and_http_errors_fall_back(self):
        cases = [
            OllamaSession(invalid_at=0, invalid_content='{"title_zh": "", "summary_zh": "x"}'),
            OllamaSession(invalid_at=0, invalid_content='{"title_zh": "標題"}'),
            OllamaSession(status=500),
        ]
        for ollama in cases:
            with self.subTest(ollama=ollama.invalid_content if ollama.status == 200 else ollama.status):
                store = self.store_with(2)
                with self.assertLogs('arxiv_digest', level='WARNING'):
                    _, bot = self.push(store, ollama)
                self.assertEqual(len(ollama.calls), 1)
                self.assertTrue(all(text.startswith('<b>Paper ') for text in self.texts(bot)))

    # ---------------- R8 ----------------

    def test_R8_disabled_or_missing_section_makes_no_request(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.ini'
            path.write_text(helpers.INI, encoding='utf-8')
            self.assertIsNone(load_config(path).translate.validated())
        for config in (Config(helpers.CONFIG.db, helpers.CONFIG.arxiv, helpers.TELEGRAM), DISABLED):
            with self.subTest(config=config.translate):
                store = self.store_with(2)
                with patch.object(cli, 'OllamaTranslator', side_effect=AssertionError('translator built')):
                    bot = helpers.BotSession()
                    telegram = lambda token, chat_id: TelegramClient(token, chat_id, session=bot)
                    with patch.object(cli, 'Store', return_value=store), patch.object(cli, 'TelegramClient', side_effect=telegram):
                        cli.run_push(config, rng=random.Random(7), sleep=lambda s: None)
                self.assertTrue(all(text.startswith('<b>Paper ') for text in self.texts(bot)))

    def test_R8_defaults_and_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'offline.ini'
            path.write_text(helpers.INI + '[TRANSLATE]\nenabled = yes\n', encoding='utf-8')
            self.assertEqual(load_config(path).translate.validated(), ('qwen3.5:9b', 'http://127.0.0.1:11434', 300.0))
            path.write_text(helpers.INI + '[TRANSLATE]\nenabled = true\nmodel = other:1b\n'
                            'url = http://gpu-box:11434/\ntimeout = 45\n', encoding='utf-8')
            self.assertEqual(load_config(path).translate.validated(), ('other:1b', 'http://gpu-box:11434', 45.0))

    def test_R8_invalid_settings_fail_before_db_and_daily_unaffected(self):
        cases = [(TranslateConfig('maybe'), 'enabled'), (TranslateConfig('true', timeout='0'), 'timeout'),
                 (TranslateConfig('true', timeout='abc'), 'timeout')]
        for translate, name in cases:
            with self.subTest(name=name, value=translate):
                config = Config(helpers.CONFIG.db, helpers.CONFIG.arxiv, helpers.TELEGRAM, translate)
                with patch.object(cli, 'load_config', return_value=config), \
                        patch.object(cli, 'Store', side_effect=AssertionError('DB opened')) as store:
                    with self.assertLogs('arxiv_digest', level='ERROR') as captured:
                        self.assertEqual(cli.main(['push']), 1)
                store.assert_not_called()
                self.assertIn(name, '\n'.join(captured.output))
                with patch.object(cli, 'load_config', return_value=config), patch.object(cli, 'run_fetch', return_value=0):
                    self.assertEqual(cli.main(['daily']), 0)

    # ---------------- D1 ----------------

    def test_D1_registered_and_offline(self):
        config = jsonlib.loads(Path('workflow.config.json').read_text(encoding='utf-8'))
        self.assertIn('tests/test_push_translation.py', config['testFiles'])
        self.push(self.store_with(2), OllamaSession())
        self.push(self.store_with(2), OllamaSession(fail_at=0))
        self.assertEqual(self.http.call_count, 0)
        self.assertEqual(self.db.call_count, 0)


if __name__ == '__main__':
    unittest.main()
