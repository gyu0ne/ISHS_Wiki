"""Small request/session guards with no database or network calls."""

from urllib.parse import urlsplit
import re

import flask


_PERSON_TEMPLATE = re.compile(r'\[include\(\s*틀:(?:인곽위키/인물|사건사고)\s*(?:,|\)\])', re.I)
_PERSON_CATEGORY = re.compile(r'\[\[\s*(?:분류|category)\s*:\s*(?:재학생|졸업생)\s*(?:\|[^\]]*)?\]\]', re.I)


def is_person_document(name, data):
    if name.lower().startswith('user:'):
        return True
    return bool(_PERSON_TEMPLATE.search(data) or _PERSON_CATEGORY.search(data))


_GET_MUTATIONS = frozenset((
    'filter_all_delete', 'user_alarm_delete', 'user_setting_key',
    'user_setting_key_delete', 'user_watch_list_name', 'user_setting_skin_set',
    'vote_end', 'vote_close', 'edit_backlink_reset', 'topic_tool_close',
    'topic_tool_stop', 'topic_tool_top', 'topic_tool_time', 'topic_tool_hide',
    'topic_tool_notice', 'topic_comment_notice', 'topic_comment_blind', 'api_w_set_reset',
))


def reset_auth_session():
    # Carry only navigation and harmless preferences across account changes.
    retained = {key: flask.session[key] for key in (
        '__login_prev_title', 'lastest_document', 'skin', 'lang',
    ) if key in flask.session}
    flask.session.clear()
    flask.session.update(retained)


def check_request_origin():
    request = flask.request
    if request.method in ('GET', 'HEAD', 'OPTIONS') and request.endpoint not in _GET_MUTATIONS:
        return

    if request.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
        flask.abort(403)

    origin = request.headers.get('Origin')
    source = origin if origin is not None else request.referrer
    if source:
        try:
            actual, expected = urlsplit(source), urlsplit(request.host_url)
            actual_port = actual.port or (443 if actual.scheme == 'https' else 80)
            expected_port = expected.port or (443 if expected.scheme == 'https' else 80)
            if (actual.scheme, actual.hostname, actual_port) == (expected.scheme, expected.hostname, expected_port):
                return
        except ValueError:
            pass
        flask.abort(403)

    # Browser fetches can omit Referer by policy; this forbidden request header
    # still proves their origin. Cookie API clients must send a matching Origin.
    if request.headers.get('Sec-Fetch-Site') == 'same-origin':
        return
    # Fetch Metadata marks address-bar navigation as "none".
    if request.method in ('GET', 'HEAD') and request.headers.get('Sec-Fetch-Site') == 'none':
        return
    flask.abort(403)


def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    return response
