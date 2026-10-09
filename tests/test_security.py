"""Exercise actual route functions without app.py's process/DB startup."""

import ast
import asyncio
from contextlib import nullcontext
import datetime
import hashlib
import hmac
import html
import importlib.util
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

import flask


ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    source = ROOT / path
    tree = ast.parse(source.read_text(encoding='utf8'))
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[name]


def load_security_module():
    spec = importlib.util.spec_from_file_location('request_security', ROOT / 'route/tool/security.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_auth_state_module():
    spec = importlib.util.spec_from_file_location('auth_state', ROOT / 'route/tool/auth_state.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_security_key_module():
    spec = importlib.util.spec_from_file_location('security_key', ROOT / 'route/tool/security_key.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'isolated-test-key'
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            create table user_set (id text, name text, data text);
            create table other (name text, data text, coverage text);
            create table login_token (user_id text, token text, expires text);
            insert into user_set values ('limited', 'acl', 'bans');
            insert into user_set values ('owner', 'pw', 'SECRET-HASH');
            insert into user_set values ('owner', 'random_key', '');
            insert into user_set values ('owner', '2fa', 'on');
        ''')
        self.namespace = {
            'flask': flask, 'html': html, '_html': html, 'datetime': datetime,
            'db_change': lambda sql: sql,
            'get_db_connect': lambda: nullcontext(self.conn),
            're_error': AsyncMock(return_value=('denied', 403)),
            'redirect': lambda conn, path: flask.redirect(path),
            'acl_check': AsyncMock(side_effect=lambda *a, **k: 0 if k.get('tool') == 'ban_auth' else 1),
            'easy_minify': lambda conn, data: data,
            'skin_check': lambda conn: 'test.html',
            'wiki_set': AsyncMock(return_value=[]),
            'wiki_custom': AsyncMock(return_value=[]),
            'wiki_css': lambda data: '',
            'url_pas': lambda data: data,
            'get_lang': lambda *a, **k: 'text',
            'captcha_post': AsyncMock(return_value=0),
            'ip_check': lambda: flask.session.get('id', '127.0.0.1'),
            'ip_or_user': lambda ip: 1 if ip == '127.0.0.1' else 0,
            'ban_check': AsyncMock(return_value=[0]),
            'pw_check': Mock(return_value=1),
            'pw_encode': lambda conn, key: 'encoded:' + key,
            'load_random_key': lambda n: 'K' * n,
            'ua_plus': Mock(), 'get_time': lambda: '2026-10-09 00:00:00',
        }
        self.app.jinja_loader = __import__('jinja2').DictLoader({'test.html': '{{ data|safe }}'})
        auth = load_auth_state_module()
        self.namespace.update(auth_pending_matches=auth.auth_pending_matches,
                              clear_login_state=auth.clear_login_state,
                              clear_logout_state=auth.clear_logout_state,
                              secrets=secrets,
                              recovery_key_hash=load_security_key_module().recovery_key_hash,
                              _RECOVERY_ALPHABET='0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
                              global_some_set_do=lambda key: 'sqlite',
                              _SUPPORTED_ENCODINGS=('sha256', 'sha3', 'sha3-512', 'sha3-salt', 'sha3-512-salt'))
        for name in ('_begin_transaction', '_recover_with_key', '_new_secret'):
            load_function('route/login_find_key.py', name, self.namespace)

    def test_new_recovery_key_is_displayed_once_and_only_verifier_is_stored(self):
        for name in ('_begin_key_transaction', '_new_recovery_key', '_replace_recovery_key', 'user_setting_key'):
            load_function('route/user_setting_key.py', name, self.namespace)
        self.conn.commit()
        with self.app.test_request_context('/change/key'):
            flask.session['id'] = 'owner'
            response = asyncio.run(self.namespace['user_setting_key']())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            key = re.search(r'value="([A-Za-z0-9]{128})"', response.get_data(as_text=True)).group(1)
            stored = self.conn.execute("select data from user_set where name = 'random_key' and id = 'owner'").fetchone()[0]
            self.assertNotEqual(stored, key)
            self.assertEqual(stored, self.namespace['recovery_key_hash'](key))

    def test_acl_only_explicit_success_boolean_grants_permission(self):
        backend = AsyncMock()
        env = {'ip_check': lambda: 'limited', 'python_to_golang': backend}
        check = load_function('route/tool/func.py', 'acl_check', env)
        for reply in ({'response': 'error', 'data': 'connection failed'}, {},
                      {'response': 'ok', 'data': 'false'},
                      {'response': 'ok', 'data': 1}, None,
                      {'response': 'ok', 'data': False}):
            with self.subTest(reply=reply):
                backend.return_value = reply
                self.assertEqual(asyncio.run(check(tool='owner_auth')), 1)
        backend.return_value = {'response': 'ok', 'data': True}
        self.assertEqual(asyncio.run(check(tool='owner_auth')), 0)

    def test_anonymous_content_search_cannot_probe_hidden_text(self):
        backend = AsyncMock(return_value=['Person'])
        self.namespace['python_to_golang'] = backend
        self.namespace['sys'] = sys
        handler = load_function('route/go_api_func_search.py', 'api_func_search', self.namespace)
        with self.app.test_request_context('/api/search_data/private'):
            self.assertEqual(asyncio.run(handler('private', 'data')), [])
            backend.assert_not_awaited()
            self.assertEqual(asyncio.run(handler('Person', 'title')), ['Person'])
        backend.reset_mock()
        with self.app.test_request_context('/api/search_data/private'):
            flask.session['id'] = 'member'
            backend.return_value = []
            self.assertEqual(asyncio.run(handler('private', 'data')), [])
            backend.assert_awaited_once()
            backend.reset_mock()
            backend.return_value = ['Person']
            self.assertEqual(asyncio.run(handler('private', 'data')), ['Person'])
            backend.assert_awaited_once()

    def admin_client(self):
        handler = load_function('route/admin_edit_user_info.py', 'admin_edit_user_info', self.namespace)
        self.app.add_url_rule('/admin/edit_user_info/<user_name>', view_func=handler, methods=['GET', 'POST'])
        return self.app.test_client()

    def test_ban_operator_cannot_promote_self_or_read_auth_fields(self):
        client = self.admin_client()
        for field in ('acl', 'pw', 'random_key', '2fa', 'custom_css', 'email'):
            with self.subTest(field=field):
                response = client.post('/admin/edit_user_info/limited?field=' + field,
                                       data={field: 'owner'})
                self.assertEqual(response.status_code, 403)
                response = client.get('/admin/edit_user_info/owner?field=' + field)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b'SECRET-HASH', response.data)
        self.assertEqual(self.conn.execute("select data from user_set where id='limited' and name='acl'").fetchone()[0], 'bans')

    def test_ban_operator_can_edit_supported_profile_field(self):
        client = self.admin_client()
        response = client.post('/admin/edit_user_info/limited?field=real_name', data={'real_name': 'Name'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.conn.execute("select data from user_set where name='real_name'").fetchone()[0], 'Name')

    def test_unauthorized_profile_request_is_a_real_denial(self):
        self.namespace['acl_check'] = AsyncMock(return_value=1)
        response = self.admin_client().post('/admin/edit_user_info/owner?field=real_name')
        self.assertEqual(response.status_code, 403)

    def test_empty_recovery_key_cannot_reset_account(self):
        handler = load_function('route/login_find_key.py', 'login_find_key', self.namespace)
        with self.app.test_request_context('/login/find/key', method='POST', data={'key': ''}):
            asyncio.run(handler())
        self.assertEqual(self.conn.execute("select data from user_set where name='pw'").fetchone()[0], 'SECRET-HASH')

    def test_second_factor_missing_secret_never_authenticates(self):
        handler = load_function('route/login_login_2fa.py', 'login_login_2fa', self.namespace)
        with self.app.test_request_context('/login/2fa', method='POST', data={'pw': ''}):
            flask.session['login_id'] = 'owner'
            load_auth_state_module().set_auth_pending(flask.session, 'login_2fa', 'owner')
            asyncio.run(handler())
            self.assertNotIn('id', flask.session)

    def test_completed_second_factor_clears_pending_identity(self):
        self.conn.executescript("insert into user_set values ('owner','2fa_pw','hash'); insert into user_set values ('owner','2fa_pw_encode','sha3');")
        self.namespace['reset_auth_session'] = lambda: flask.session.clear()
        handler = load_function('route/login_login_2fa.py', 'login_login_2fa', self.namespace)
        with self.app.test_request_context('/login/2fa', method='POST', data={'pw': 'factor'}):
            flask.session['login_id'] = 'owner'
            load_auth_state_module().set_auth_pending(flask.session, 'login_2fa', 'owner')
            asyncio.run(handler())
            self.assertEqual(flask.session.get('id'), 'owner')
            self.assertNotIn('login_id', flask.session)

    def test_password_verification_rejects_bad_second_factor(self):
        self.conn.executescript("insert into user_set values ('owner','2fa_pw','hash'); insert into user_set values ('owner','2fa_pw_encode','sha3');")
        self.namespace['pw_check'].return_value = 0
        handler = load_function('route/login_login_2fa.py', 'login_login_2fa', self.namespace)
        with self.app.test_request_context('/login/2fa', method='POST', data={'pw': 'wrong'}):
            flask.session['login_id'] = 'owner'
            load_auth_state_module().set_auth_pending(flask.session, 'login_2fa', 'owner')
            asyncio.run(handler())
            self.assertNotIn('id', flask.session)

    def test_recovery_key_sql_metacharacters_are_bound(self):
        handler = load_function('route/login_find_key.py', 'login_find_key', self.namespace)
        with self.app.test_request_context('/login/find/key', method='POST', data={'key': "' OR 1=1 --"}):
            asyncio.run(handler())
        self.assertEqual(self.conn.execute("select data from user_set where name='pw'").fetchone()[0], 'SECRET-HASH')

    def test_raw_api_filters_private_docs_without_an_extra_backend_call(self):
        backend = AsyncMock()
        env = {'sys': sys, 'python_to_golang': backend, 'ip_check': self.namespace['ip_check'],
               'ip_or_user': self.namespace['ip_or_user'], 'is_person_document': load_security_module().is_person_document,
               'cache_view_context': lambda *args: None}
        handler = load_function('route/go_api_w_raw.py', 'api_w_raw', env)
        for name, text in (('user:owner', 'PRIVATE'), ('Person', '[include( 틀:인곽위키/인물 )]PRIVATE'),
                           ('Person', '[[분류:재학생]]PRIVATE'), ('Incident', '[include(틀:사건사고)]PRIVATE'),
                           ('Person', '[include(틀:인곽위키/인물, name=x)]PRIVATE')):
            with self.subTest(name=name, text=text), self.app.test_request_context('/'):
                backend.reset_mock()
                backend.return_value = {'response': 'ok', 'data': text}
                self.assertEqual(asyncio.run(handler(name)), {'response': 'require auth'})
                self.assertEqual(backend.await_count, 1)
                flask.session['id'] = 'member'
                self.assertEqual(asyncio.run(handler(name)), backend.return_value)
        with self.app.test_request_context('/'):
            backend.return_value = {'response': 'ok', 'data': 'PUBLIC'}
            self.assertEqual(asyncio.run(handler('Public')), backend.return_value)

    def test_user_info_anonymous_response_omits_sensitive_profile_values(self):
        self.conn.executescript("create table data (title text, data text); insert into user_set values ('owner','real_name','PRIVATE-NAME'); insert into user_set values ('owner','birth_year','PRIVATE-YEAR');")
        self.namespace.update(ip_pas=AsyncMock(return_value='owner'), level_check=AsyncMock(return_value=['0','0','0']),
                              acl_check=AsyncMock(return_value=1))
        handler = load_function('route/api_user_info.py', 'api_user_info', self.namespace)
        with self.app.test_request_context('/'):
            response = asyncio.run(handler('owner'))
            self.assertNotIn(b'PRIVATE-', response.data)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json, {'error': 'login_required'})
            flask.session['id'] = 'member'
            self.assertEqual(asyncio.run(handler('owner')).json['data']['real_name'], 'PRIVATE-NAME')

    def test_guest_view_does_not_read_description_after_raw_privacy_denial(self):
        backend = AsyncMock(return_value={'response':'require auth'})
        self.namespace['api_w_raw'] = backend
        handler = load_function('route/view_w.py', 'view_w', self.namespace)
        statements = []
        self.conn.set_trace_callback(statements.append)
        for reply in ({'response': 'require auth'}, {'response': 'ok'}, None,
                      {'response': 'ok', 'title': 'Other', 'data': 'private'},
                      {'response': 'ok', 'title': 'ParamPerson', 'data': None}):
            for user in (None, 'no-view'):
                backend.reset_mock()
                backend.return_value = reply
                with self.app.test_request_context('/w/ParamPerson'):
                    if user:
                        flask.session['id'] = user
                    result = asyncio.run(handler('ParamPerson'))
                self.assertEqual(result, ('denied', 403))
                self.assertEqual(statements, [])
                backend.assert_awaited_once_with('ParamPerson')

    def test_account_transition_drops_script_and_auth_cache(self):
        reset = load_security_module().reset_auth_session
        with self.app.test_request_context('/'):
            flask.session.update(id='attacker', head='<script>attack()</script>',
                                 head_ringo='script', login_id='owner', c_key='key',
                                 user_generation='1', __login_prev_title='Home', lang='ko-KR')
            reset()
            self.assertEqual(dict(flask.session), {'__login_prev_title': 'Home', 'lang': 'ko-KR'})

    def test_logout_clears_every_skin_head_and_preserves_preferences(self):
        clear = load_auth_state_module().clear_logout_state
        with self.app.test_request_context('/'):
            flask.session.update(id='attacker', head='<script>global</script>',
                                 headmarisa='<script>skin</script>', head_ringo='<script>skin2</script>',
                                 lang='ko-KR', skin='marisa')
            clear(flask.session)
            self.assertEqual(dict(flask.session), {'lang': 'ko-KR', 'skin': 'marisa'})

    def test_synchronous_auto_login_preserves_token_validation_and_session_reset(self):
        self.namespace.update(app=self.app, hashlib=hashlib, hmac=hmac,
                              reset_auth_session=load_security_module().reset_auth_session)
        handler = load_function('app.py', 'check_auto_login', self.namespace)
        self.assertFalse(asyncio.iscoroutinefunction(handler))
        expires = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        self.conn.execute('insert into login_token values (?,?,?)',
                          ('owner', hashlib.sha256(b'valid-token').hexdigest(), expires))
        with self.app.test_request_context('/', headers={'Cookie':'auto_login=owner:valid-token'}):
            flask.session['head'] = '<script>stale()</script>'
            handler()
            self.assertEqual(flask.session['id'], 'owner')
            self.assertTrue(flask.session['auto_login_checked'])
            self.assertNotIn('head', flask.session)
        for cookie in ('owner:wrong-token', 'malformed-token'):
            with self.app.test_request_context('/', headers={'Cookie':'auto_login=' + cookie}):
                handler()
                self.assertNotIn('id', flask.session)
        self.conn.execute("update login_token set expires='2000-01-01 00:00:00'")
        with self.app.test_request_context('/', headers={'Cookie':'auto_login=owner:valid-token'}):
            handler()
            self.assertNotIn('id', flask.session)
        statements = []
        self.conn.set_trace_callback(statements.append)
        with self.app.test_request_context('/'):
            flask.session['id'] = 'member'
            handler()
        self.assertEqual(statements, [])


class RequestSecurityTest(unittest.TestCase):
    def setUp(self):
        self.module = load_security_module()
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'origin-tests'
        self.app.before_request(self.module.check_request_origin)
        self.app.after_request(self.module.add_security_headers)
        self.app.add_url_rule('/mutation', endpoint='mutation', view_func=lambda: 'ok', methods=['POST', 'PATCH', 'PUT', 'DELETE'])
        self.app.add_url_rule('/view', endpoint='view', view_func=lambda: 'view')
        self.app.add_url_rule('/legacy-delete', endpoint='filter_all_delete', view_func=lambda: 'deleted')
        self.client = self.app.test_client()

    def test_same_origin_forms_and_ajax_work(self):
        for method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            for headers in ({'Origin': 'http://localhost'}, {'Referer': 'http://localhost/form'},
                            {'Sec-Fetch-Site': 'same-origin'}, {'Origin': 'http://localhost:80'}):
                with self.subTest(method=method, headers=headers):
                    self.assertEqual(self.client.open('/mutation', method=method, headers=headers).status_code, 200)

    def test_foreign_missing_null_and_sibling_origins_are_blocked(self):
        for headers in ({}, {'Origin': 'null'}, {'Origin': 'https://evil.example'},
                        {'Referer': 'http://localhost.evil.example/form'},
                        {'Origin': 'http://localhost:81'},
                        {'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-site'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post('/mutation', headers=headers).status_code, 403)

    def test_cross_site_safe_read_stays_available(self):
        response = self.client.get('/view', headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_legacy_get_mutation_requires_provenance(self):
        self.assertEqual(self.client.get('/legacy-delete', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
        self.assertEqual(self.client.get('/legacy-delete').status_code, 403)
        self.assertEqual(self.client.get('/legacy-delete', headers={'Referer': 'http://localhost/filter'}).status_code, 200)
        self.assertEqual(self.client.get('/legacy-delete', headers={'Sec-Fetch-Site': 'none'}).status_code, 200)

    def test_production_app_runs_origin_guard_before_other_hooks(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf8'))
        first_hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_general_flood_guard')
        self.assertEqual(ast.unparse(first_hook.body[0]), 'check_request_origin()')
        after_hook = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_redirect_login_to_last_doc')
        self.assertEqual(ast.unparse(after_hook.body[-1]), 'return add_security_headers(response)')


class ImageSecurityTest(unittest.TestCase):
    def test_uploaded_svg_is_sandboxed_and_images_keep_content(self):
        module = load_security_module()
        namespace = {'flask': flask, 're': re, 'get_db_connect': lambda: nullcontext(None),
                     'acl_check': AsyncMock(return_value=0), 'load_image_url': lambda conn: 'images'}
        handler = load_function('route/main_view_image.py', 'main_view_image', namespace)
        app = flask.Flask(__name__)
        with app.test_request_context('/image/test.svg'), unittest.mock.patch.object(
            flask, 'send_from_directory', return_value=flask.Response('<svg/>', mimetype='image/svg+xml')):
            response = asyncio.run(handler('test.svg'))
            self.assertEqual(response.data, b'<svg/>')
            self.assertIn('sandbox', response.headers['Content-Security-Policy'])
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')


class BackendBinarySecurityTest(unittest.TestCase):
    def test_missing_or_modified_backend_is_rejected_before_startup(self):
        spec = importlib.util.spec_from_file_location('backend_security', ROOT / 'route/tool/backend_security.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            import os
            import json
            try:
                os.chdir(directory)
                manifest = Path('route_go/security/manifest.json')
                manifest.parent.mkdir(parents=True)
                binary = Path('backend.bin')
                binary.write_bytes(b'approved backend bytes')
                manifest.write_text(json.dumps({'files':{binary.name:hashlib.sha256(binary.read_bytes()).hexdigest()}}))
                module.verify_backend(binary)
                binary.write_bytes(b'old or tampered backend')
                with self.assertRaises(RuntimeError):
                    module.verify_backend(binary)
                binary.unlink()
                with self.assertRaises(RuntimeError):
                    module.verify_backend(binary)
            finally:
                os.chdir(original)


if __name__ == '__main__':
    unittest.main()
