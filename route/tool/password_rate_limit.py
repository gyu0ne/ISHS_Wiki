import hashlib
import json
import math
import time


_ATTEMPT_LIMIT = 5
_WINDOW_SECONDS = 60
_CLEANUP_LIMIT = 100
_TABLE = 'password_rate_limit'


def initialize_password_rate_limit(conn, db_type):
    cursor = conn.cursor()
    try:
        if db_type == 'sqlite':
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS ' + _TABLE + ' ('
                'bucket_key TEXT PRIMARY KEY, '
                'attempts_json TEXT NOT NULL, '
                'expires_at REAL NOT NULL'
                ')'
            )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS password_rate_limit_expires '
                'ON ' + _TABLE + ' (expires_at)'
            )
        elif db_type == 'mysql':
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS ' + _TABLE + ' ('
                'bucket_key CHAR(64) NOT NULL PRIMARY KEY, '
                'attempts_json TEXT NOT NULL, '
                'expires_at DOUBLE NOT NULL, '
                'INDEX password_rate_limit_expires (expires_at)'
                ') ENGINE=InnoDB'
            )
        else:
            raise ValueError('Unsupported database type: ' + str(db_type))

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cursor.close()


def consume_password_attempt(
    conn,
    db_type,
    account,
    client_ip,
    scope='password',
    now=None,
):
    requested_time = None if now is None else float(now)
    if requested_time is not None and not math.isfinite(requested_time):
        raise ValueError('now must be finite')

    keys = sorted((
        _bucket_key('account', scope, account),
        _bucket_key('client_ip', scope, client_ip),
    ))
    if db_type == 'sqlite':
        return _consume_sqlite(conn, keys, requested_time)
    if db_type == 'mysql':
        return _consume_mysql(conn, keys, requested_time)
    raise ValueError('Unsupported database type: ' + str(db_type))


def _bucket_key(bucket_type, scope, value):
    identity = json.dumps(
        [str(scope), bucket_type, str(value)],
        ensure_ascii=False,
        separators=(',', ':'),
    )
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def _decode_attempts(payload, current_time):
    values = json.loads(payload)
    if not isinstance(values, list):
        raise ValueError('Invalid password rate-limit data')

    attempts = []
    cutoff = current_time - _WINDOW_SECONDS
    for value in values:
        timestamp = float(value)
        if not math.isfinite(timestamp):
            raise ValueError('Invalid password rate-limit timestamp')
        if timestamp > cutoff:
            attempts.append(timestamp)
    attempts.sort()
    return attempts


def _prepare_updates(rows, keys, current_time):
    attempts_by_key = {
        row[0]: _decode_attempts(row[1], current_time)
        for row in rows
    }
    if set(attempts_by_key) != set(keys):
        raise RuntimeError('Password rate-limit bucket is missing')

    blocked_until = [
        attempts[0] + _WINDOW_SECONDS
        for attempts in attempts_by_key.values()
        if len(attempts) >= _ATTEMPT_LIMIT
    ]
    if blocked_until:
        retry_seconds = max(1, int(math.ceil(max(blocked_until) - current_time)))
    else:
        retry_seconds = 0
        for attempts in attempts_by_key.values():
            attempts.append(current_time)
            attempts.sort()

    updates = []
    for key in keys:
        attempts = attempts_by_key[key]
        expires_at = attempts[-1] + _WINDOW_SECONDS if attempts else current_time + _WINDOW_SECONDS
        updates.append((
            json.dumps(attempts, separators=(',', ':')),
            expires_at,
            key,
        ))
    return retry_seconds, updates


def _consume_sqlite(conn, keys, requested_time):
    cursor = conn.cursor()
    try:
        cursor.execute('BEGIN IMMEDIATE')
        current_time = time.time() if requested_time is None else requested_time
        cursor.execute(
            'DELETE FROM ' + _TABLE + ' WHERE bucket_key IN ('
            'SELECT bucket_key FROM ' + _TABLE + ' '
            'WHERE expires_at <= ? ORDER BY bucket_key LIMIT ?'
            ')',
            (current_time, _CLEANUP_LIMIT),
        )
        for key in keys:
            cursor.execute(
                'INSERT OR IGNORE INTO ' + _TABLE + ' '
                '(bucket_key, attempts_json, expires_at) VALUES (?, ?, ?)',
                (key, '[]', current_time + _WINDOW_SECONDS),
            )
        cursor.execute(
            'SELECT bucket_key, attempts_json FROM ' + _TABLE + ' '
            'WHERE bucket_key IN (?, ?) ORDER BY bucket_key',
            tuple(keys),
        )
        retry_seconds, updates = _prepare_updates(cursor.fetchall(), keys, current_time)
        cursor.executemany(
            'UPDATE ' + _TABLE + ' SET attempts_json = ?, expires_at = ? '
            'WHERE bucket_key = ?',
            updates,
        )
        conn.commit()
        return retry_seconds
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def _consume_mysql(conn, keys, requested_time):
    cursor = conn.cursor()
    try:
        cursor.execute('START TRANSACTION')
        insert_time = time.time() if requested_time is None else requested_time
        for key in keys:
            cursor.execute(
                'INSERT INTO ' + _TABLE + ' '
                '(bucket_key, attempts_json, expires_at) VALUES (%s, %s, %s) '
                'ON DUPLICATE KEY UPDATE bucket_key = bucket_key',
                (key, '[]', insert_time + _WINDOW_SECONDS),
            )
        current_time = time.time() if requested_time is None else requested_time
        cursor.execute(
            'SELECT bucket_key, attempts_json FROM ' + _TABLE + ' '
            'WHERE bucket_key IN (%s, %s) ORDER BY bucket_key FOR UPDATE',
            tuple(keys),
        )
        retry_seconds, updates = _prepare_updates(cursor.fetchall(), keys, current_time)
        cursor.executemany(
            'UPDATE ' + _TABLE + ' SET attempts_json = %s, expires_at = %s '
            'WHERE bucket_key = %s',
            updates,
        )
        conn.commit()
        _cleanup_mysql(conn, cursor, current_time)
        return retry_seconds
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cursor.close()


def _cleanup_mysql(conn, cursor, current_time):
    try:
        cursor.execute(
            'DELETE FROM ' + _TABLE + ' WHERE expires_at <= %s '
            'ORDER BY bucket_key LIMIT ' + str(_CLEANUP_LIMIT),
            (current_time,),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
