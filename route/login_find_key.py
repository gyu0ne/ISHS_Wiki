from .tool.func import *
import secrets


_RECOVERY_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SUPPORTED_ENCODINGS = ("sha256", "sha3", "sha3-512", "sha3-salt", "sha3-512-salt")


def _begin_transaction(conn):
    if global_some_set_do("db_type") == "sqlite":
        conn.cursor().execute("BEGIN IMMEDIATE")
    else:
        conn.begin()


def _new_secret(length):
    return ''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(length))


def _recover_with_key(conn, input_key, new_password):
    if input_key == '':
        return None

    curs = conn.cursor()
    _begin_transaction(conn)
    try:
        curs.execute(db_change(
            'select id from user_set where name = "random_key" and data = ?'
        ), [input_key])
        key_rows = curs.fetchall()
        if len(key_rows) != 1:
            conn.rollback()
            return None

        user_id = key_rows[0][0]
        curs.execute(db_change(
            'select data from user_set where name = "encode" and id = ?'
        ), [user_id])
        encode_rows = curs.fetchall()
        encodings = {'sha3' if row[0] == '' else row[0] for row in encode_rows}
        if len(encodings) != 1 or not encodings.issubset(_SUPPORTED_ENCODINGS):
            conn.rollback()
            return None
        encoding = next(iter(encodings))

        curs.execute(db_change(
            'select data from user_set where name = "pw" and id = ?'
        ), [user_id])
        password_count = len(curs.fetchall())
        if password_count == 0:
            conn.rollback()
            return None

        curs.execute(db_change(
            'delete from user_set where name = "random_key" and id = ? and data = ?'
        ), [user_id, input_key])
        if curs.rowcount != 1:
            conn.rollback()
            return None

        encoded_password = pw_encode(conn, new_password, encoding)
        curs.execute(db_change(
            'update user_set set data = ? where name = "pw" and id = ?'
        ), [encoded_password, user_id])
        curs.execute(db_change(
            'select data from user_set where name = "pw" and id = ?'
        ), [user_id])
        password_rows = curs.fetchall()
        if len(password_rows) != password_count or any(
            row[0] != encoded_password for row in password_rows
        ):
            conn.rollback()
            return None

        curs.execute(db_change(
            "update user_set set data = '' where name = '2fa' and id = ? and data != ''"
        ), [user_id])
        conn.commit()
        return user_id
    except Exception:  # noqa: BROAD_EXCEPT_OK - transaction boundary must roll back before propagation
        conn.rollback()
        raise


async def login_find_key():
    with get_db_connect() as conn:
        curs = conn.cursor()
        if flask.request.method == 'POST':
            if await captcha_post(conn, flask.request.form.get('g-recaptcha-response', flask.request.form.get('g-recaptcha', ''))) == 1:
                return await re_error(conn, 13)

            input_key = flask.request.form.get('key', '')
            key = _new_secret(32)
            user_id = _recover_with_key(conn, input_key, key)
            if user_id is None:
                return redirect(conn, '/user')

            curs.execute(db_change('select data from other where name = "reset_user_text"'))
            sql_d = curs.fetchall()
            b_text = (sql_d[0][0] + '<hr class="main_hr">') if sql_d and sql_d[0][0] != '' else ''

            response = flask.make_response(easy_minify(conn, flask.render_template(skin_check(conn),
                    imp = [get_lang(conn, 'reset_user_ok'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                    data = '' + \
                        b_text + \
                        get_lang(conn, 'id') + ' : ' + user_id + \
                        '<hr class="main_hr">' + \
                        get_lang(conn, 'password') + ' : ' + key + \
                    '',
                    menu = [['user', get_lang(conn, 'return')]]
                )))
            response.headers['Cache-Control'] = 'no-store'
            return response
        else:
            return easy_minify(conn, flask.render_template(skin_check(conn),
                imp = [get_lang(conn, 'password_search'), await wiki_set(), await wiki_custom(conn), wiki_css([0, 0])],
                data = '''
                    <form method="post">
                        <input placeholder="''' + get_lang(conn, 'key') + '''" name="key" type="password">
                        <hr class="main_hr">
                        ''' + await captcha_get(conn) + '''
                        <button type="submit">''' + get_lang(conn, 'send') + '''</button>
                    </form>
                ''',
                menu = [['user', get_lang(conn, 'return')]]
            ))
