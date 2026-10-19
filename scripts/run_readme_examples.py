#!/usr/bin/env python3
"""Run every Python example in README.md against a live Hardcharger server, as written.

Starts hardcharger-server (SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY) the way the README assumes
one: port 31337, TLS with a certificate for localhost, user ``hardcharger`` with password
``change-me``, and certificate sign-in where ``client.pem`` signs in. The test CA is trusted
through SSL_CERT_FILE (which the driver's Go TLS reads on Linux), so the examples need no
TLS settings. Each ```python block runs in a fresh interpreter in one scratch directory; a
```text block right after one must appear in its output (whitespace-normalized). Any failure,
or a README with no Python examples, exits non-zero.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.hardcharger_server import make_certificates, start_server, stop_server  # noqa: E402

README_PORT = 31337
README_USER = "hardcharger"
README_PASSWORD = "change-me"
CLIENT_IDENTITY = "analyst@example.com"
FENCE = re.compile(pattern=r"^```(\w*)\n(.*?)^```", flags=re.MULTILINE | re.DOTALL)


def examples(readme: str) -> list[tuple[str, str | None]]:
    """(code, expected output or None) for each ```python block."""
    blocks = [(match.group(1), match.group(2)) for match in FENCE.finditer(string=readme)]
    found = []
    for index, (language, body) in enumerate(blocks):
        if language != "python":
            continue
        expected = None
        if index + 1 < len(blocks) and blocks[index + 1][0] == "text":
            expected = blocks[index + 1][1]
        found.append((body, expected))
    return found


def normalized(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    readme = (ROOT / "README.md").read_text()
    blocks = examples(readme=readme)
    if not blocks:
        print("README.md has no Python examples", file=sys.stderr)
        return 1
    work = pathlib.Path(tempfile.mkdtemp(prefix="readme-examples-"))
    certs = make_certificates(out_dir=work / "certs", admin_identity=CLIENT_IDENTITY)
    server = start_server(
        workdir=work / "server",
        certs=certs,
        port=README_PORT,
        username=README_USER,
        password=README_PASSWORD,
        admin_cert_identity=CLIENT_IDENTITY,
    )
    failures = 0
    try:
        run_dir = work / "run"
        run_dir.mkdir()
        shutil.copyfile(src=certs["admin"], dst=run_dir / "client.pem")
        shutil.copyfile(src=certs["admin-key"], dst=run_dir / "client-key.pem")
        env = {key: value for key, value in os.environ.items() if not key.startswith("HARDCHARGER_")}
        env["SSL_CERT_FILE"] = str(certs["ca"])
        env["HARDCHARGER_TOKEN"] = server.password_token()
        for number, (code, expected) in enumerate(blocks, start=1):
            first_line = code.strip().splitlines()[0]
            print(f"--- example {number}: {first_line}", flush=True)
            result = subprocess.run(
                args=[sys.executable, "-c", code],
                cwd=run_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            print(result.stdout, end="")
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                print(f"FAILED: example {number} exited {result.returncode}", file=sys.stderr)
                failures += 1
            elif expected is not None and normalized(text=expected) not in normalized(text=result.stdout):
                print(f"FAILED: example {number}'s output doesn't contain:\n{expected}", file=sys.stderr)
                failures += 1
    finally:
        stop_server(server=server)
    print(f"{len(blocks) - failures} of {len(blocks)} README examples passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
