"""Windows runtime selection and packaged executable trust boundaries."""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_backend_security', ROOT / 'route/tool/backend_security.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def select_backend(system, machine):
    tree = ast.parse((ROOT / 'route/tool/func.py').read_text(encoding='utf8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'linux_exe_chmod')
    namespace = {'platform': SimpleNamespace(system=lambda: system, machine=lambda: machine)}
    if hasattr(backend, 'backend_executable_name'):
        namespace['backend_executable_name'] = lambda: backend.backend_executable_name(system, machine)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'route/tool/func.py'), 'exec'), namespace)
    return namespace['linux_exe_chmod']()


class WindowsBackendTest(unittest.TestCase):
    def test_existing_supported_platforms_select_their_executable(self):
        for system, machine, expected in [
            ('Windows', 'AMD64', 'main.amd64.exe'),
            ('Windows', 'x86_64', 'main.amd64.exe'),
            ('Windows', 'ARM64', 'main.arm64.exe'),
            ('Windows', 'aarch64', 'main.arm64.exe'),
            ('Linux', 'x86_64', 'main.amd64.bin'),
            ('Linux', 'aarch64', 'main.arm64.bin'),
            ('Darwin', 'arm64', 'main.mac.arm64.bin'),
        ]:
            with self.subTest(system=system, machine=machine):
                self.assertEqual(select_backend(system, machine), expected)

    def test_windows_executables_match_the_pinned_manifest(self):
        manifest = json.loads((ROOT / 'route_go/security/manifest.json').read_text())
        for name in ('main.amd64.exe', 'main.arm64.exe'):
            with self.subTest(binary=name):
                binary = ROOT / 'route_go/bin' / name
                with binary.open('rb') as stream:
                    header = stream.read(64)
                    self.assertEqual(header[:2], b'MZ')
                    stream.seek(struct.unpack_from('<I', header, 60)[0])
                    self.assertEqual(stream.read(4), b'PE\0\0')
                    self.assertEqual(struct.unpack('<H', stream.read(2))[0],
                                     0x8664 if name == 'main.amd64.exe' else 0xaa64)
                    stream.seek(0)
                    self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(), manifest['files'][name])

    def test_windows_architecture_aliases_are_consistent(self):
        for machine in ('AMD64', 'amd64', 'x86_64', 'x64'):
            with self.subTest(machine=machine):
                self.assertEqual(backend.backend_executable_name('Windows', machine), 'main.amd64.exe')
        for machine in ('ARM64', 'arm64', 'aarch64'):
            with self.subTest(machine=machine):
                self.assertEqual(backend.backend_executable_name('Windows', machine), 'main.arm64.exe')

    def test_unknown_platform_does_not_launch_an_unrelated_binary(self):
        for system, machine in [('Windows', 'x86'), ('Linux', 'i686'), ('FreeBSD', 'amd64')]:
            with self.subTest(system=system, machine=machine):
                with self.assertRaisesRegex(RuntimeError, 'Unsupported backend platform'):
                    select_backend(system, machine)

    def test_unapproved_windows_executable_is_rejected(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path('route_go/security').mkdir(parents=True)
                binary = Path('main.amd64.exe')
                binary.write_bytes(b'MZ-approved-fixture')
                manifest = Path('route_go/security/manifest.json')
                manifest.write_text(json.dumps({'files': {binary.name: hashlib.sha256(binary.read_bytes()).hexdigest()}}))
                backend.verify_backend(binary)
                binary.write_bytes(b'MZ-old-unapproved-fixture')
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    backend.verify_backend(binary)
                binary.unlink()
                with self.assertRaises(RuntimeError):
                    backend.verify_backend(binary)
            finally:
                os.chdir(original)


@unittest.skipUnless(os.name == 'nt', 'Windows launcher execution requires Windows')
class WindowsLauncherTest(unittest.TestCase):
    def launch_probe(self, environment=None):
        with tempfile.TemporaryDirectory(prefix='wiki windows ') as directory:
            root = Path(directory)
            project = root / '기존 서버 위키'
            project.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            tools = root / 'tools'
            tools.mkdir()
            shutil.copyfile(ROOT / 'run_windows.bat', project / 'run_windows.bat')
            (project / 'app.py').write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "Path('probe.json').write_text(json.dumps({'cwd':str(Path.cwd()),"
                "'prefix':sys.prefix,'arguments':sys.argv[1:]}),encoding='utf8')\n",
                encoding='utf8')
            (tools / 'pip3.bat').write_bytes(b'@echo off\r\necho called>pip-called\r\n')
            if environment:
                subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(project / environment)],
                               check=True, capture_output=True, timeout=60)
            env = os.environ.copy()
            env.pop('PYTHONHOME', None)
            env.pop('PYTHONPATH', None)
            env['PATH'] = os.pathsep.join((str(tools), str(Path(sys.executable).parent), env['PATH']))
            result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', 'call',
                                     str(project / 'run_windows.bat'), 'dev'],
                                    cwd=outside, env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            probe = json.loads((project / 'probe.json').read_text(encoding='utf8'))
            self.assertEqual(Path(probe['cwd']), project)
            self.assertEqual(probe['arguments'], ['dev'])
            self.assertFalse((project / 'pip-called').exists())
            self.assertFalse((outside / 'pip-called').exists())
            expected = project / environment if environment else Path(sys.prefix)
            self.assertEqual(Path(probe['prefix']), expected)

    def test_launcher_uses_existing_virtual_environment_from_another_directory(self):
        for environment in ('.venv', 'venv'):
            with self.subTest(environment=environment):
                self.launch_probe(environment)

    def test_launcher_uses_existing_path_python(self):
        self.launch_probe()


if __name__ == '__main__':
    unittest.main()
