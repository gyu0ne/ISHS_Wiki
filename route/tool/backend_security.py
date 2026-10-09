"""Verify packaged backend bytes once at startup, never on web requests."""

import hashlib
import json
from pathlib import Path


def verify_backend(path):
    binary = Path(path)
    manifest_path = Path('route_go/security/manifest.json')
    try:
        expected = json.loads(manifest_path.read_text(encoding='utf8'))['files'][binary.name]
        with binary.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError('Install the secured Go binary and route_go/security/manifest.json; build with python route_go/security/build_backend.py') from error
    if digest != expected:
        raise RuntimeError('Go backend checksum mismatch; refusing to run an unverified binary')
