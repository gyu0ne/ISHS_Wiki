"""비밀번호 입력 제한이 실제 경로에서 적용되는지 검사합니다."""

import asyncio
import contextlib
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import flask


ROOT = Path(__file__).resolve().parents[1]
USER_ID = 'test-account'
USER_NAME = 'test-user'


def _load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _RouteEnvironment:
    def __init__(self):
        self.db_path = None
        self.captcha_calls = 0
        self.password_calls = 0
        self.riro_check = mock.Mock(return_value={
            'status': 'error',
            'message': '인증 실패',
        })

    @contextlib.contextmanager
    def get_db_connect(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def ip_check(self):
        return flask.session.get('id', flask.request.remote_addr or 'unknown')

    @staticmethod
    def ip_or_user(value):
        return 1 if '.' in value or ':' in value else 0

    async def ban_check(self, *args, **kwargs):
        return [0]

    async def captcha_post(self, *args, **kwargs):
        self.captcha_calls += 1
        return 0

    async def re_error(self, conn, code):
        return flask.make_response('오류:' + str(code), 400)

    def pw_check(self, conn, supplied, stored, encoding, user_id):
        self.password_calls += 1
        return int(supplied == 'correct')


class PasswordAttemptRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = _RouteEnvironment()
        cls.saved_requests = sys.modules.get('requests')
        cls.saved_modules = {
            name: module for name, module in sys.modules.items()
            if name == 'route' or name.startswith('route.')
        }
        for name in list(cls.saved_modules):
            sys.modules.pop(name, None)

        route_package = types.ModuleType('route')
        route_package.__path__ = [str(ROOT / 'route')]
        tool_package = types.ModuleType('route.tool')
        tool_package.__path__ = [str(ROOT / 'route' / 'tool')]
        sys.modules['route'] = route_package
        sys.modules['route.tool'] = tool_package

        func_module = types.ModuleType('route.tool.func')
        cls._install_func_stubs(func_module)
        sys.modules['route.tool.func'] = func_module

        riro_auth = types.ModuleType('route.riroschoolauth')
        riro_auth.check_riro_login = cls.env.riro_check
        sys.modules['route.riroschoolauth'] = riro_auth
        sys.modules['requests'] = types.ModuleType('requests')

        reauth_target = types.ModuleType('route.riro_reauth_target')
        reauth_target.REAUTH_YEAR = 2026
        reauth_target.REAUTH_TARGET_GENERATIONS = (30, 31, 32)
        sys.modules['route.riro_reauth_target'] = reauth_target

        cls.storage = _load_module(
            'route.tool.password_rate_limit',
            'route/tool/password_rate_limit.py',
        )
        cls.adapter = _load_module(
            'route.tool.password_attempt',
            'route/tool/password_attempt.py',
        )
        cls.login = _load_module('route.login_login', 'route/login_login.py')
        cls.second_factor = _load_module(
            'route.login_login_2fa',
            'route/login_login_2fa.py',
        )
        cls.change_password = _load_module(
            'route.user_setting_pw',
            'route/user_setting_pw.py',
        )
        cls.riro_login = _load_module(
            'route.riro_login_page',
            'route/riro_login_page.py',
        )
        cls.riro_reauth = _load_module(
            'route.riro_reauth',
            'route/riro_reauth.py',
        )

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules):
            if name == 'route' or name.startswith('route.'):
                sys.modules.pop(name, None)
        sys.modules.update(cls.saved_modules)
        if cls.saved_requests is None:
            sys.modules.pop('requests', None)
        else:
            sys.modules['requests'] = cls.saved_requests

    @classmethod
    def _install_func_stubs(cls, module):
        env = cls.env
        module.flask = flask
        module.get_db_connect = env.get_db_connect
        module.ip_check = env.ip_check
        module.ip_or_user = env.ip_or_user
        module.ban_check = env.ban_check
        module.captcha_post = env.captcha_post
        module.re_error = env.re_error
        module.pw_check = env.pw_check
        module.db_change = lambda query: query
        module.redirect = lambda conn, path: flask.redirect(path)
        module.acl_check = cls._return_zero
        module.ua_plus = lambda *args, **kwargs: None
        module.get_time = lambda: '2026-09-11 00:00:00'
        module.pw_encode = lambda conn, value: value
        module.number_check = lambda value: value
        module.easy_minify = lambda conn, value: value
        module.get_lang = lambda conn, key: {
            'error': '오류',
            'password_attempt_limit': '{seconds}초 후 다시 시도해 주세요.',
        }.get(key, key)
        module.global_some_set_do = lambda key: 'sqlite' if key == 'db_type' else None
        module.skin_check = lambda conn: 'skin.html'
        module.wiki_css = lambda value: ''
        module.wiki_custom = cls._return_empty
        module.wiki_set = cls._return_empty
        module.captcha_get = cls._return_empty
        module.http_warning = lambda conn: ''

    @staticmethod
    async def _return_zero(*args, **kwargs):
        return 0

    @staticmethod
    async def _return_empty(*args, **kwargs):
        return ''

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env.db_path = str(Path(self.temp_dir.name) / 'test.db')
        self.env.captcha_calls = 0
        self.env.password_calls = 0
        self.env.riro_check.reset_mock()
        self.riro_login.check_riro_login = self.env.riro_check
        self.riro_reauth.check_riro_login = self.env.riro_check
        self._create_database()

        self.app = flask.Flask(__name__)
        self.app.testing = True
        self.app.secret_key = 'test-secret'
        self.app.add_url_rule('/login', 'login', self._sync(self.login.login_login), methods=['GET', 'POST'])
        self.app.add_url_rule(
            '/login/2fa', 'second_factor',
            self._sync(self.second_factor.login_login_2fa),
            methods=['GET', 'POST'],
        )
        self.app.add_url_rule(
            '/change/pw', 'change_password',
            self._sync(self.change_password.user_setting_pw),
            methods=['GET', 'POST'],
        )
        self.app.add_url_rule(
            '/riro_login', 'riro_login',
            self._sync(self.riro_login.riro_login_page),
            methods=['GET', 'POST'],
        )
        self.app.add_url_rule(
            '/riro_reauth', 'riro_reauth',
            self._sync(self.riro_reauth.riro_reauth),
            methods=['GET', 'POST'],
        )
        self.render_patch = mock.patch.object(
            flask,
            'render_template',
            side_effect=lambda template, **context: context.get('data', ''),
        )
        self.render_patch.start()

    def tearDown(self):
        self.render_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _sync(async_handler):
        def view():
            return asyncio.run(async_handler())

        return view

    def _create_database(self):
        conn = sqlite3.connect(self.env.db_path)
        try:
            conn.execute('CREATE TABLE user_set (id TEXT, name TEXT, data TEXT)')
            conn.execute('CREATE TABLE other (name TEXT, data TEXT)')
            conn.executemany(
                'INSERT INTO user_set (id, name, data) VALUES (?, ?, ?)',
                [
                    (USER_ID, 'user_name', USER_NAME),
                    (USER_ID, 'pw', 'stored-password'),
                    (USER_ID, 'encode', 'test'),
                    (USER_ID, 'student_id', '2601'),
                    (USER_ID, 'generation', '32'),
                    (USER_ID, '2fa_pw', 'stored-second-factor'),
                    (USER_ID, '2fa_pw_encode', 'test'),
                ],
            )
            self.storage.initialize_password_rate_limit(conn, 'sqlite')
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _post(client, path, data, remote_addr='127.0.0.1', headers=None):
        return client.post(
            path,
            data=data,
            headers=headers or {},
            environ_base={'REMOTE_ADDR': remote_addr},
        )

    def test_sixth_login_stops_before_captcha_and_password_check(self):
        client = self.app.test_client()
        for attempt in range(5):
            response = self._post(
                client,
                '/login',
                {'id': USER_NAME, 'pw': 'wrong'},
                remote_addr='10.0.0.' + str(attempt + 1),
            )
            self.assertNotEqual(response.status_code, 429)

        response = self._post(
            client,
            '/login',
            {'id': USER_NAME, 'pw': 'correct'},
            remote_addr='10.0.0.99',
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.env.captcha_calls, 5)
        self.assertEqual(self.env.password_calls, 5)
        self.assertIn('Retry-After', response.headers)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_successful_fifth_login_and_new_session_do_not_clear_attempts(self):
        for attempt in range(4):
            client = self.app.test_client()
            response = self._post(
                client,
                '/login',
                {'id': USER_NAME, 'pw': 'wrong'},
                remote_addr='10.1.0.' + str(attempt + 1),
            )
            self.assertNotEqual(response.status_code, 429)

        fifth_client = self.app.test_client()
        fifth = self._post(
            fifth_client,
            '/login',
            {'id': USER_NAME, 'pw': 'correct'},
            remote_addr='10.1.0.5',
        )
        sixth_client = self.app.test_client()
        sixth = self._post(
            sixth_client,
            '/login',
            {'id': USER_NAME, 'pw': 'correct'},
            remote_addr='10.1.0.6',
        )

        self.assertEqual(fifth.status_code, 302)
        self.assertEqual(sixth.status_code, 429)
        self.assertEqual(self.env.password_calls, 5)

    def test_get_requests_and_forged_ip_headers_do_not_change_the_budget(self):
        client = self.app.test_client()
        for _ in range(8):
            self.assertEqual(client.get('/login').status_code, 200)

        for attempt in range(5):
            response = self._post(
                client,
                '/login',
                {'id': 'missing-' + str(attempt), 'pw': 'wrong'},
                headers={
                    'X-Real-IP': '198.51.100.' + str(attempt + 1),
                    'CF-Connecting-IP': '203.0.113.' + str(attempt + 1),
                },
            )
            self.assertNotEqual(response.status_code, 429)

        blocked = self._post(
            client,
            '/login',
            {'id': 'another-missing-user', 'pw': 'wrong'},
            headers={'X-Real-IP': '192.0.2.1', 'CF-Connecting-IP': '192.0.2.2'},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_cooldown_expiry_allows_a_new_login_attempt(self):
        with mock.patch.object(self.storage.time, 'time', return_value=1_000.0):
            for attempt in range(5):
                response = self._post(
                    self.app.test_client(),
                    '/login',
                    {'id': USER_NAME, 'pw': 'wrong'},
                    remote_addr='10.2.0.' + str(attempt + 1),
                )
                self.assertNotEqual(response.status_code, 429)
            blocked = self._post(
                self.app.test_client(),
                '/login',
                {'id': USER_NAME, 'pw': 'correct'},
                remote_addr='10.2.0.6',
            )
        with mock.patch.object(self.storage.time, 'time', return_value=1_060.0):
            allowed = self._post(
                self.app.test_client(),
                '/login',
                {'id': USER_NAME, 'pw': 'correct'},
                remote_addr='10.2.0.7',
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(allowed.status_code, 302)

    def test_current_password_shares_login_budget_but_second_factor_does_not(self):
        for attempt in range(4):
            response = self._post(
                self.app.test_client(),
                '/login',
                {'id': USER_NAME, 'pw': 'wrong'},
                remote_addr='10.3.0.' + str(attempt + 1),
            )
            self.assertNotEqual(response.status_code, 429)

        settings_client = self.app.test_client()
        with settings_client.session_transaction() as session:
            session['id'] = USER_ID
        fifth = self._post(
            settings_client,
            '/change/pw',
            {
                'password_now': 'wrong',
                'password_new': 'new-password',
                'password_new_repeat': 'new-password',
            },
            remote_addr='10.3.0.5',
        )
        blocked = self._post(
            self.app.test_client(),
            '/login',
            {'id': USER_NAME, 'pw': 'correct'},
            remote_addr='10.3.0.6',
        )
        blocked_change = self._post(
            settings_client,
            '/change/pw',
            {
                'password_now': 'correct',
                'password_new': 'new-password',
                'password_new_repeat': 'new-password',
            },
            remote_addr='10.3.0.7',
        )
        self.assertEqual(blocked_change.status_code, 429)
        self.assertEqual(self.env.password_calls, 5)
        with self.env.get_db_connect() as conn:
            stored = conn.execute(
                "SELECT data FROM user_set WHERE id = ? AND name = 'pw'",
                (USER_ID,),
            ).fetchone()[0]
        self.assertEqual(stored, 'stored-password')

        second_factor_client = self.app.test_client()
        with second_factor_client.session_transaction() as session:
            session['login_id'] = USER_ID
        for attempt in range(5):
            second_factor = self._post(
                second_factor_client,
                '/login/2fa',
                {'pw': 'wrong'},
                remote_addr='10.3.1.' + str(attempt + 1),
            )
            self.assertNotEqual(second_factor.status_code, 429)
        blocked_second_factor = self._post(
            second_factor_client,
            '/login/2fa',
            {'pw': 'correct'},
            remote_addr='10.3.1.6',
        )

        self.assertNotEqual(fifth.status_code, 429)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked_second_factor.status_code, 429)

    def test_riro_routes_share_casefolded_account_and_stop_external_checks(self):
        aliases = [' StudentOne ', 'studentone', 'STUDENTONE', ' studentone ']
        for attempt, alias in enumerate(aliases):
            response = self._post(
                self.app.test_client(),
                '/riro_login',
                {'riro_id': alias, 'riro_pw': 'wrong'},
                remote_addr='10.4.0.' + str(attempt + 1),
            )
            self.assertNotEqual(response.status_code, 429)

        reauth_client = self.app.test_client()
        with reauth_client.session_transaction() as session:
            session['id'] = USER_ID
        fifth = self._post(
            reauth_client,
            '/riro_reauth',
            {'riro_id': 'StudentOne', 'riro_pw': 'wrong'},
            remote_addr='10.4.0.5',
        )
        sixth = self._post(
            self.app.test_client(),
            '/riro_login',
            {'riro_id': 'studentone', 'riro_pw': 'correct'},
            remote_addr='10.4.0.6',
        )

        self.assertNotEqual(fifth.status_code, 429)
        self.assertEqual(sixth.status_code, 429)
        self.assertEqual(self.env.riro_check.call_count, 5)


if __name__ == '__main__':
    unittest.main()
