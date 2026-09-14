import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import flask

from route.tool.request_rate_limit import (
    check_request_rate_limit,
    reset_request_rate_limit,
    _LIMIT,
)

# app.py의 _general_flood_guard()와 동일한 로직을 가진 최소 Flask 앱으로,
# app.py 전체(실제 DB 연결/Go 백엔드 기동)를 임포트하지 않고도
# before_request 배선이 실제 HTTP 응답으로 올바르게 이어지는지 확인한다.

_RATE_LIMIT_EXEMPT_PREFIXES = ('/views/', '/image/', '/file/', '/robots.txt', '/ads.txt', '/sitemap')


def build_test_app():
    app = flask.Flask(__name__)

    @app.before_request
    def _general_flood_guard():
        path = flask.request.path
        if path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
            return

        client_ip = flask.request.headers.get('X-Test-IP', flask.request.remote_addr)
        retry_after = check_request_rate_limit(client_ip)
        if retry_after:
            response = flask.Response('Too Many Requests', status=429)
            response.headers['Retry-After'] = str(retry_after)
            return response

    @app.route('/w/<name>')
    def view_doc(name):
        return 'doc:' + name

    @app.route('/views/main.css')
    def static_asset():
        return 'css'

    return app


class TestFloodGuardIntegration(unittest.TestCase):
    def setUp(self):
        reset_request_rate_limit()
        self.client = build_test_app().test_client()

    def test_requests_within_limit_return_200(self):
        for _ in range(_LIMIT):
            resp = self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.1'})
            self.assertEqual(resp.status_code, 200)

    def test_request_over_limit_returns_429_with_retry_after(self):
        for _ in range(_LIMIT):
            self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.2'})

        resp = self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.2'})
        self.assertEqual(resp.status_code, 429)
        self.assertIn('Retry-After', resp.headers)
        self.assertGreater(int(resp.headers['Retry-After']), 0)

    def test_static_assets_are_exempt_from_the_limit(self):
        for _ in range(_LIMIT + 20):
            resp = self.client.get('/views/main.css', headers={'X-Test-IP': '10.0.0.3'})
            self.assertEqual(resp.status_code, 200)

    def test_different_clients_are_not_cross_blocked(self):
        for _ in range(_LIMIT):
            self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.4'})

        blocked = self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.4'})
        self.assertEqual(blocked.status_code, 429)

        other_client = self.client.get('/w/test', headers={'X-Test-IP': '10.0.0.5'})
        self.assertEqual(other_client.status_code, 200)


if __name__ == '__main__':
    unittest.main()
