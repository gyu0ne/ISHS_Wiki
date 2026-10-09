"""Build the existing pinned Go backend with its secured entry point.

Go is a build-time tool only; the application uses the resulting standalone
binary. Run from any directory: python route_go/security/build_backend.py.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


REVISION = '12c83d5379ac4ae4c3d9069e407d0b5928359758'
ROOT = Path(__file__).resolve().parents[1]
SECURITY = Path(__file__).resolve().parent
TARGETS = {
    'windows-amd64': 'main.amd64.exe',
    'windows-arm64': 'main.arm64.exe',
    'linux-amd64': 'main.amd64.bin',
    'linux-arm64': 'main.arm64.bin',
    'darwin-arm64': 'main.mac.arm64.bin',
}


def build(source, go, targets):
    manifest_path = SECURITY / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'revision': REVISION, 'files': {}}
    if manifest['revision'] != REVISION:
        raise RuntimeError('Unexpected backend source revision')
    shutil.copyfile(SECURITY / 'main.go', source / 'main.go')
    overlays = sorted((SECURITY / 'overlay').rglob('*.go'))
    for overlay in overlays:
        relative = overlay.relative_to(SECURITY / 'overlay')
        destination = source / relative
        if not destination.is_file():
            raise RuntimeError('Pinned source is missing overlay target: ' + str(relative))
        shutil.copyfile(overlay, destination)
    env = os.environ.copy()
    env['CGO_ENABLED'] = '0'
    (ROOT / 'bin').mkdir(exist_ok=True)
    for target in targets:
        env['GOOS'], env['GOARCH'] = target.split('-')
        binary = ROOT / 'bin' / TARGETS[target]
        subprocess.run([go, 'build', '-mod=mod', '-trimpath', '-o', str(binary), '.'], cwd=source, env=env, check=True)
        manifest['files'][binary.name] = hashlib.sha256(binary.read_bytes()).hexdigest()
        binary.chmod(0o755)
    manifest['entrypoint_sha256'] = hashlib.sha256((SECURITY / 'main.go').read_bytes()).hexdigest()
    manifest['overlay_sha256'] = {p.relative_to(SECURITY / 'overlay').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in overlays}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Existing clean checkout of the exact pinned revision')
    parser.add_argument('--go', default='go', help='Path to Go compiler')
    parser.add_argument('--target', action='append', choices=TARGETS)
    args = parser.parse_args()
    args.go = shutil.which(args.go) or str(Path(args.go).resolve())
    targets = args.target or list(TARGETS)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'backend'
        if args.source:
            observed = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
            if observed != REVISION:
                raise RuntimeError('Source must use the pinned backend revision')
            if subprocess.check_output(['git', '-C', str(args.source), 'status', '--porcelain'], text=True).strip():
                raise RuntimeError('Source checkout must be clean')
            shutil.copytree(args.source, source, ignore=shutil.ignore_patterns('.git', 'bin', 'go.sum'))
        else:
            url = 'https://api.github.com/repos/openNAMU/Discard-GopenNAMU-3/tarball/' + REVISION
            request = urllib.request.Request(url, headers={'User-Agent': 'ISHS-Wiki-backend-builder'})
            with urllib.request.urlopen(request, timeout=60) as response:
                archive = response.read()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(directory, filter='data')
            source = next(p for p in Path(directory).iterdir() if p.is_dir())
        build(source, args.go, targets)


if __name__ == '__main__':
    main()
