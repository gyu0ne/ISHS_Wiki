from .tool.func import *
import secrets
import html
from .tool.security_key import recovery_key_hash


_RECOVERY_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _begin_key_transaction(conn):
    if global_some_set_do("db_type") == "sqlite":
        conn.cursor().execute("BEGIN IMMEDIATE")
    else:
        conn.begin()


def _new_recovery_key():
    return ''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(128))


def _replace_recovery_key(conn, user_id, key):
    curs = conn.cursor()
    _begin_key_transaction(conn)
    try:
        curs.execute(db_change(
            "delete from user_set where name = 'random_key' and id = ?"
        ), [user_id])
        curs.execute(db_change(
            "insert into user_set (name, id, data) values ('random_key', ?, ?)"
        ), [user_id, recovery_key_hash(key)])
        conn.commit()
    except Exception:  # noqa: BROAD_EXCEPT_OK - transaction boundary must roll back before propagation
        conn.rollback()
        raise


async def user_setting_key():
    with get_db_connect() as conn:
        curs = conn.cursor()

        ip = ip_check()
        if ip_or_user(ip) == 0:
            while 1:
                key = _new_recovery_key()
                curs.execute(db_change(
                    'select data from user_set where name = "random_key" and data = ?'
                ), [recovery_key_hash(key)])
                if not curs.fetchall():
                    break

            _replace_recovery_key(conn, ip, key)
            response = flask.make_response(easy_minify(conn, flask.render_template(skin_check(conn),
                imp=[get_lang(conn, 'key'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data='<p>복구 키는 지금 한 번만 표시됩니다. 안전한 곳에 저장하세요. 새 키를 만들면 이전 키는 사용할 수 없습니다.</p>'
                     '<input readonly aria-label="복구 키" value="' + html.escape(key, quote=True) + '">',
                menu=[['change', get_lang(conn, 'return')]])))
            response.headers['Cache-Control'] = 'no-store'
            return response

        return redirect(conn, '/change')
