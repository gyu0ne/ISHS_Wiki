"""Use canonical Go view permissions; reuse public context within one request."""
import flask
import requests
import sqlite3


def ensure_include_acl_index(conn):
    # Reuse the existing SQLite cache and avoid full document/ACL scans.
    # Indexes are built once; the partial ACL index stores only view rules.
    if isinstance(conn, sqlite3.Connection):
        conn.execute("create index if not exists security_view_acl_index on acl (title) where type = 'view'")
        conn.execute("create index if not exists security_document_title_index on data (title)")


def _state(identity):
    current = getattr(flask.g, 'include_permissions', None)
    if current is None or current['identity'] != identity:
        current = {'identity': identity, 'context': None, 'titles': {}, 'backend_failed': False}
        flask.g.include_permissions = current
    return current


def cache_view_context(reply, identity):
    if not flask.has_request_context() or not isinstance(reply, dict) or reply.get('response') != 'ok':
        return
    context = reply.get('view_context')
    if (isinstance(context, dict) and type(context.get('normal')) is bool
            and type(context.get('public')) is bool):
        _state(identity)['context'] = context


def _call_acl(name, identity):
    # Lazy import avoids a cycle with func -> renderer -> this module.
    from .func import global_some_set_do, ip_check, json_dumps
    port = str(global_some_set_do('setup_golang_port') or '')
    token = global_some_set_do('internal_api_token')
    if (identity != ip_check() or not token or not port.isascii()
            or not port.isdigit() or not 1 <= int(port) <= 65535):
        return None
    payload = {'url': 'api_func_acl', 'ip': identity, 'cookie': '',
               'session': json_dumps(dict(flask.session)),
               'data': json_dumps({'name': name, 'tool': 'render', 'topic_number': ''})}
    try:
        with requests.Session() as connection:
            connection.trust_env = False
            response = connection.post('http://127.0.0.1:' + str(int(port)) + '/',
                data=json_dumps(payload), headers={'X-OpenNAMU-Internal-Token': token},
                timeout=(0.5, 2), allow_redirects=False)
            if response.status_code != 200:
                return None
            reply = response.json()
            if not isinstance(reply, dict) or reply.get('response') != 'ok' or type(reply.get('data')) is not bool:
                return None
            context = reply.get('view_context')
            if not isinstance(context, dict) or any(type(context.get(k)) is not bool for k in ('normal', 'public')):
                return None
            return reply
    except (requests.RequestException, ValueError):
        return None


def check_include_acl(name, rules, identity):
    if not flask.has_request_context():
        return False
    state = _state(identity)
    if state['backend_failed']:
        return False
    # Ambiguous duplicate rules use the canonical database reader.
    public_rule = len(rules) <= 1 and (not rules or rules[0] in ('', 'normal', 'all', 'ban'))
    if public_rule:
        if state['context'] is None:
            reply = _call_acl('', identity)
            if reply is None:
                state['backend_failed'] = True
                return False
            cache_view_context(reply, identity)
        key = 'public' if rules and rules[0] in ('all', 'ban') else 'normal'
        return state['context'][key] is True
    if name not in state['titles']:
        reply = _call_acl(name, identity)
        if reply is None:
            state['backend_failed'] = True
            return False
        cache_view_context(reply, identity)
        state['titles'][name] = reply['data'] is True
    return state['titles'][name]
