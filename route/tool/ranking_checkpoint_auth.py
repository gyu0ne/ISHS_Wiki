"""Authenticate lightweight metadata and bind the unchanged compressed payload."""

from hashlib import sha256
from functools import lru_cache
import hmac
import json
import re

from .security_key import derived_key
from .ranking_replay_checkpoint import InvalidCheckpoint

MAX_METADATA_CHARS = 4 * 1024 * 1024
_HEADER = re.compile(r'^\{"_security":\{"v":1,"payload_sha256":"([0-9a-f]{64})","mac":"([0-9a-f]{64})","opaque":([01])\}(?:,|(?=\}))')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCheckpoint('Duplicate checkpoint metadata key')
        result[key] = value
    return result


def _parse(metadata):
    if not isinstance(metadata, str) or len(metadata) > MAX_METADATA_CHARS:
        raise InvalidCheckpoint('Checkpoint metadata size exceeded')
    try:
        value = json.loads(metadata, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise InvalidCheckpoint('Invalid checkpoint metadata') from error
    if not isinstance(value, dict):
        raise InvalidCheckpoint('Expected checkpoint metadata object')
    return value


@lru_cache(maxsize=1)
def _checkpoint_key():
    return derived_key(b'opennamu-checkpoint-v1')


def _mac(title, digest, metadata, opaque):
    title_bytes = title.encode('utf-8')
    context = len(title_bytes).to_bytes(4, 'big') + title_bytes + digest.encode('ascii') + bytes((opaque,))
    return hmac.digest(_checkpoint_key(), context + metadata.encode('utf-8'), 'sha256').hex()


def sign_checkpoint(title, metadata, payload):
    if not isinstance(metadata, str) or len(metadata) > MAX_METADATA_CHARS:
        raise InvalidCheckpoint('Checkpoint metadata size exceeded')
    try:
        value = _parse(metadata)
    except InvalidCheckpoint:
        # The store also supports opaque metadata in its standalone API.
        metadata = json.dumps({'opaque_metadata': metadata}, ensure_ascii=False, separators=(',', ':'))
        opaque = 1
    else:
        if '_security' in value:
            raise InvalidCheckpoint('Reserved checkpoint metadata key')
        metadata = metadata.strip() if value else '{}'
        opaque = 0
    digest = sha256(payload.encode('utf-8')).hexdigest()
    signature = _mac(title, digest, metadata, opaque)
    # Keep original metadata fields and payload format. Verifying this fixed
    # header authenticates exact JSON bytes without parsing them a second time.
    header = json.dumps({'_security': {'v': 1, 'payload_sha256': digest, 'mac': signature,
                                     'opaque': opaque}}, separators=(',', ':'))
    return header if metadata == '{}' else header[:-1] + ',' + metadata[1:]


def verify_checkpoint(title, metadata, payload=None):
    if not isinstance(metadata, str) or len(metadata) > MAX_METADATA_CHARS:
        raise InvalidCheckpoint('Checkpoint metadata size exceeded')
    match = _HEADER.match(metadata)
    if match is None:
        raise InvalidCheckpoint('Unauthenticated checkpoint')
    digest, signature, opaque = match.groups()
    original = '{' + metadata[match.end():]
    if not hmac.compare_digest(signature, _mac(title, digest, original, int(opaque))):
        raise InvalidCheckpoint('Checkpoint metadata changed')
    if payload is not None and not hmac.compare_digest(digest, sha256(payload.encode('utf-8')).hexdigest()):
        raise InvalidCheckpoint('Checkpoint payload changed')
    return _parse(original)['opaque_metadata'] if opaque == '1' else original


def _authenticated_metadata(metadata):
    """Unwrap bytes already authenticated by a matching whole-set digest."""
    match = _HEADER.match(metadata)
    if match is None:
        raise InvalidCheckpoint('Unauthenticated checkpoint')
    original = '{' + metadata[match.end():]
    return _parse(original)['opaque_metadata'] if match.group(3) == '1' else original


class CheckpointVerification:
    """Per-cache 32-byte memo; changed DB bytes always require fresh MACs."""

    __slots__ = ('digest',)

    def __init__(self):
        self.digest = None

    @staticmethod
    def fingerprint(rows):
        digest = sha256(b'opennamu-authenticated-checkpoint-set-v1')
        for title, metadata in rows:
            if not isinstance(title, str) or not isinstance(metadata, str) or len(metadata) > MAX_METADATA_CHARS:
                return None
            title_bytes = title.encode('utf-8')
            metadata_bytes = metadata.encode('utf-8')
            digest.update(len(title_bytes).to_bytes(4, 'big') + title_bytes
                          + len(metadata_bytes).to_bytes(8, 'big') + metadata_bytes)
        return digest.digest()
