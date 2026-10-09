# Secured internal backend

The original `version.json` selects GopenNAMU `v2025-04-28-v1`. This entry point
comes from [openNAMU/Discard-GopenNAMU-3](https://github.com/openNAMU/Discard-GopenNAMU-3)
at commit `12c83d5379ac4ae4c3d9069e407d0b5928359758`. It listens on
`127.0.0.1` and requires the per-process `NAMU_INTERNAL_TOKEN` on every request.
The ACL and raw endpoints also return request-local view context, using facts
already read by the canonical ACL checker. This avoids another backend call for
public includes during ordinary page rendering. Restricted includes still check
the canonical document ACL, once per distinct title within a request.
The existing ACL policy and Go dependencies are retained. Its BSD
license is included in `LICENSE`.

Windows x64 and ARM64 executables are included in `main`, together with their
checksum manifest. A checkout or GitHub source ZIP can run `python app.py`
without installing Go or downloading another archive. `run_windows.bat` starts
from the project directory and uses an existing `.venv`, `venv`, or PATH Python.
Stop the existing server before replacing these files, and preserve the DB,
configuration and `app_session/security.key`.

For Linux/macOS, use the supplied backend archive for your platform, or build
from source with Python 3.11+ and Go 1.24.1+:

```sh
python route_go/security/build_backend.py
# Build only the platform you run:
python route_go/security/build_backend.py --target linux-amd64
```

For an existing clean checkout of that exact upstream revision, use
`--source /path/to/backend`. `--go /path/to/go` selects a compiler. The script
uses the pinned upstream source and existing modules, replaces `main.go` and
the four checked-in ACL/search overlays, and writes source and binary hashes to
`manifest.json`. A build downloads source and
modules when they are not already available. Go is needed only while building.

`app.py` checks the binary hash once before opening the database, generates the
internal token, and starts the backend. Missing, old, or modified binaries stop
startup. Do not replace these binaries with the unauthenticated upstream release
or expose the internal port through a reverse proxy. The default port is still
3001; `NAMU_GOLANGPORT` and the existing database setting remain supported.

The hash manifest prevents accidentally launching a different binary. It does
not protect against an attacker who can modify the application files and manifest
or read the application's process environment.
