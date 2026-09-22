from .tool.func import *
import secrets


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
        ), [user_id, key])
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
                ), [key])
                if not curs.fetchall():
                    break

            _replace_recovery_key(conn, ip, key)

        return redirect(conn, '/change')
