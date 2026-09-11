import flask

from .func import (
    easy_minify, get_lang, global_some_set_do, skin_check,
    wiki_css, wiki_custom, wiki_set,
)
from .password_rate_limit import consume_password_attempt


async def password_attempt_limit(conn, account, scope='password'):
    # 기존 ProxyFix가 처리한 주소를 사용하고 별도 IP 헤더는 신뢰하지 않습니다.
    retry_after = consume_password_attempt(
        conn, global_some_set_do('db_type'), account,
        flask.request.remote_addr or 'unknown', scope=scope,
    )
    if retry_after == 0:
        return None

    message = get_lang(conn, 'password_attempt_limit').format(seconds=retry_after)
    response = flask.make_response(easy_minify(conn, flask.render_template(
        skin_check(conn),
        imp=[get_lang(conn, 'error'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
        data='<p>' + message + '</p>',
        menu=0,
    )), 429)
    response.headers['Retry-After'] = str(retry_after)
    response.headers['Cache-Control'] = 'no-store'
    return response
