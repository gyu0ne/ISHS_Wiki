import sqlite3
import unittest
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock, patch

import flask

try:
    from .test_render_math import get_db_table_list, render_set
except ImportError:
    from test_render_math import get_db_table_list, render_set

from route.tool import include_security
from route.tool.func_tool import ip_check
from route.edit import edit


class PrivateIncludeTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.addCleanup(self.conn.close)
        for table, columns in get_db_table_list().items():
            self.conn.execute('create table ' + table + ' (' + ', '.join(c + " text default ''" for c in columns) + ')')
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'include-test'
        self.conn.executemany('insert into data (title, data) values (?, ?)', [
            ('user:owner', 'PROFILE-SECRET'),
            ('Person', '[[분류:재학생]]PERSON-SECRET'),
            ('Public', 'PUBLIC-TEXT'),
            ('Secret', 'OWNER-ONLY-SECRET'),
        ])
        self.conn.execute("insert into acl (title,type,data) values ('Secret','view','owner')")

    def render(self, name, logged_in=False):
        with self.app.test_request_context('/'):
            if logged_in:
                flask.session['id'] = 'member'
            include_security.cache_view_context(
                {'response':'ok', 'view_context':{'normal':True, 'public':True}}, ip_check())
            return render_set(self.conn, doc_name='test', doc_data='[include(' + name + ')]',
                              data_type='view', markup='namumark')

    def test_guest_cannot_extract_private_document_by_include(self):
        for name, secret in (('user:owner', 'PROFILE-SECRET'), ('Person', 'PERSON-SECRET')):
            with self.subTest(name=name):
                self.assertNotIn(secret, self.render(name))
                self.assertIn(secret, self.render(name, logged_in=True))

    def test_public_include_still_works(self):
        with patch.object(include_security, '_call_acl', side_effect=AssertionError('Extra public ACL call')):
            self.assertIn('PUBLIC-TEXT', self.render('Public'))

    def test_partial_index_is_idempotent_and_serves_only_view_rules(self):
        for _ in range(2):
            include_security.ensure_include_acl_index(self.conn)
        plan = self.conn.execute("explain query plan select data from acl where title = 'Secret' and type = 'view'").fetchall()
        self.assertTrue(any('security_view_acl_index' in str(row) for row in plan), plan)
        self.assertEqual(self.conn.execute("select count(*) from sqlite_master where name='security_view_acl_index'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("select data from acl where title='Secret'").fetchone()[0], 'owner')
        plan = self.conn.execute("explain query plan select data from data where title = 'Public'").fetchall()
        self.assertTrue(any('security_document_title_index' in str(row) for row in plan), plan)

    def test_member_cannot_render_owner_only_include(self):
        denied = {'response':'ok', 'data':False, 'view_context':{'normal':True, 'public':True}}
        with patch.object(include_security, '_call_acl', return_value=denied) as call:
            self.assertNotIn('OWNER-ONLY-SECRET', self.render('Secret', logged_in=True))
            call.assert_called_once_with('Secret', 'member')

    def test_edit_load_checks_source_before_reading_its_body(self):
        statements = []
        self.conn.set_trace_callback(statements.append)
        check = AsyncMock(side_effect=lambda name='', tool='', **kwargs:
                          1 if name == 'Secret' and tool == 'render' else 0)
        with self.app.test_request_context('/edit_from/Public'), patch.multiple(
                'route.edit', get_db_connect=Mock(return_value=nullcontext(self.conn)),
                acl_check=check, do_title_length_check=Mock(return_value=0),
                re_error=AsyncMock(return_value=('denied', 403))):
            flask.session.update(id='member', edit_load_document='Secret')
            result = self.app.ensure_sync(edit)('Public', do_type='load')
        self.assertEqual(result, ('denied', 403))
        check.assert_any_await('Secret', 'render')
        self.assertFalse(any("select data from data where title = 'Secret'" in sql for sql in statements))

    def test_restricted_checks_are_cached_only_within_same_request_and_identity(self):
        denied = {'response':'ok', 'data':False, 'view_context':{'normal':True, 'public':True}}
        allowed = dict(denied, data=True)
        with patch.object(include_security, '_call_acl', side_effect=[denied, allowed, denied]) as call:
            with self.app.test_request_context('/'):
                for _ in range(3):
                    self.assertFalse(include_security.check_include_acl('Secret', ['owner'], 'member'))
                self.assertTrue(include_security.check_include_acl('Secret', ['owner'], 'owner'))
            with self.app.test_request_context('/'):
                self.assertFalse(include_security.check_include_acl('Secret', ['owner'], 'member'))
            self.assertEqual(call.call_count, 3)

    def test_uncached_public_context_requires_only_one_call(self):
        reply = {'response':'ok', 'data':True, 'view_context':{'normal':True, 'public':True}}
        with self.app.test_request_context('/'), patch.object(include_security, '_call_acl', return_value=reply) as call:
            for title in ('Public', 'Other', 'Public'):
                self.assertTrue(include_security.check_include_acl(title, [], 'member'))
            call.assert_called_once_with('', 'member')

    def test_group_view_and_read_ban_context_are_enforced(self):
        with self.app.test_request_context('/'):
            include_security.cache_view_context(
                {'response':'ok', 'view_context':{'normal':False, 'public':True}}, 'no-view')
            self.assertFalse(include_security.check_include_acl('Public', [], 'no-view'))
            self.assertTrue(include_security.check_include_acl('Public', ['all'], 'no-view'))
            include_security.cache_view_context(
                {'response':'ok', 'view_context':{'normal':False, 'public':False}}, 'banned')
            self.assertFalse(include_security.check_include_acl('Public', ['all'], 'banned'))

    def test_backend_failure_denies_restricted_and_public_includes(self):
        with self.app.test_request_context('/'), patch.object(include_security, '_call_acl', return_value=None) as call:
            self.assertFalse(include_security.check_include_acl('Secret', ['owner'], 'member'))
            self.assertFalse(include_security.check_include_acl('Public', [], 'member'))
            call.assert_called_once()
