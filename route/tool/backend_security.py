"""Verify packaged backend bytes once at startup, never on web requests."""

import hashlib
import json
from pathlib import Path
import platform


def backend_executable_name(system=None, machine=None):
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    architecture = {'amd64': 'amd64', 'x86_64': 'amd64', 'x64': 'amd64',
                    'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine.lower())
    if architecture and system in ('Windows', 'Linux'):
        extension = 'exe' if system == 'Windows' else 'bin'
        return 'main.' + architecture + '.' + extension
    if system == 'Darwin' and architecture == 'arm64':
        return 'main.mac.arm64.bin'
    raise RuntimeError('Unsupported backend platform: ' + system + '/' + machine)


def verify_backend(path):
    binary = Path(path)
    manifest_path = Path('route_go/security/manifest.json')
    try:
        expected = json.loads(manifest_path.read_text(encoding='utf8'))['files'][binary.name]
        with binary.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError('Missing secured backend (' + binary.name + '); restore the executable and route_go/security/manifest.json from the same main version. Windows executables are included in main.') from error
    if digest != expected:
        raise RuntimeError('Go backend checksum mismatch (' + binary.name + '); restore the executable and route_go/security/manifest.json from the same main version')
