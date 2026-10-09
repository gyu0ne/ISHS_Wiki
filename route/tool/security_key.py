"""A persistent local key, independent of database contents."""

from functools import lru_cache
from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import tempfile


def read_security_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(prefix='.security-key-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(secrets.token_bytes(32))
                output.flush()
                os.fsync(output.fileno())
            try:
                # Publish a complete file without replacing another process's key.
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    if path.is_symlink():
        raise RuntimeError('Security key must be a regular private file')
    with path.open('rb') as source:
        key = source.read(33)
    if len(key) != 32:
        raise RuntimeError('Invalid security key file; restore its backup')
    return key


@lru_cache(maxsize=1)
def security_key() -> bytes:
    return read_security_key(Path(os.getenv('NAMU_SECURITY_KEY_FILE', 'app_session/security.key')))


def derived_key(context: bytes) -> bytes:
    return hmac.new(security_key(), context, sha256).digest()


def session_key(database_key: str) -> bytes:
    return derived_key(b'opennamu-session-v1\0' + database_key.encode('utf-8'))


def recovery_key_hash(key: str) -> str:
    return 'hmac-v1:' + hmac.new(derived_key(b'opennamu-recovery-v1'),
                               key.encode('utf-8'), sha256).hexdigest()


def migrate_recovery_keys(connection, sql):
    """Keep users' existing keys usable while removing their plaintext from DB."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id, data FROM user_set WHERE name = 'random_key' AND data != ''")
        for user_id, key in cursor.fetchall():
            if not key.startswith('hmac-v1:'):
                cursor.execute(sql("UPDATE user_set SET data = ? WHERE id = ? AND name = 'random_key' AND data = ?"),
                               (recovery_key_hash(key), user_id, key))
    finally:
        cursor.close()
