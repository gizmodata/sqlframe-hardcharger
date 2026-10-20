"""Real ``hardcharger-server`` processes for the integration tests.

The server binary comes from ``SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY`` (CI copies it out of
``ghcr.io/gizmodata/hardcharger:main``). Without it, or if the server doesn't come up, the tests
FAIL; they never skip. Each server listens on a free 127.0.0.1 port with an in-memory database
and a fresh admin password containing ``:`` and ``@``, and gets a clean environment: no
``HARDCHARGER_*`` variable of the shell running the tests reaches it, so a developer's real
settings or credentials can't leak in.
"""

from __future__ import annotations

import dataclasses
import datetime
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SERVER_BINARY_ENV = "SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY"
USERNAME = "sqlframe_test"
#: The e-mail identity of the client certificate that signs in as the administrator.
ADMIN_CERT_IDENTITY = "sqlframe-admin@example.com"
#: A client certificate the server knows nothing about.
STRANGER_CERT_IDENTITY = "stranger@example.com"


@dataclasses.dataclass
class Server:
    host: str
    port: int
    password: str
    process: subprocess.Popen
    log: Path
    tls: bool = False
    ca: Path | None = None
    username: str = USERNAME

    @property
    def base_url(self) -> str:
        return f"{'https' if self.tls else 'http'}://{self.host}:{self.port}"

    @property
    def uri(self) -> str:
        """The server's hardcharger:// URI (TLS unless the server serves plain HTTP)."""
        if self.tls:
            return f"hardcharger://{self.host}:{self.port}"
        return f"hardcharger://{self.host}:{self.port}?tls=false"

    def connect_kwargs(self) -> dict:
        """Keyword arguments of adbc_driver_hardcharger.dbapi.connect() for the admin user."""
        kwargs = {"uri": self.uri, "username": self.username, "password": self.password}
        if self.ca is not None:
            kwargs["tls_root_certs"] = str(self.ca)
        return kwargs

    def password_token(self) -> str:
        """An access token from the password grant (spec 4.1), fetched over plain HTTP(S)."""
        context = ssl.create_default_context(cafile=str(self.ca)) if self.tls else None
        request = urllib.request.Request(
            url=f"{self.base_url}/warp/v1/auth/token",
            data=json.dumps(
                obj={"grant_type": "password", "username": self.username, "password": self.password}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(url=request, timeout=10, context=context) as response:
            return json.loads(s=response.read())["access_token"]

    def log_tail(self, lines: int = 40) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-lines:])
        except OSError:
            return ""


def free_port() -> int:
    with socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def server_binary() -> str:
    binary = os.environ.get(SERVER_BINARY_ENV)
    if not binary:
        pytest.fail(
            reason=f"set {SERVER_BINARY_ENV} to a hardcharger-server binary (from "
            "ghcr.io/gizmodata/hardcharger:main, /opt/hardcharger/bin/hardcharger-server) to run "
            "the integration tests"
        )
    if not os.access(path=binary, mode=os.X_OK):
        pytest.fail(reason=f"{SERVER_BINARY_ENV}={binary} is not an executable")
    return binary


def clean_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("HARDCHARGER_")}


def _wait_up(server: Server, timeout: float = 60) -> None:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url=f"{server.base_url}/warp", timeout=2, context=context):
                return
        except (urllib.error.URLError, OSError) as error:
            last_error = error
        time.sleep(0.1)
    stop_server(server=server)
    pytest.fail(
        reason=f"hardcharger-server did not answer at {server.base_url}/warp "
        f"({last_error}); its log:\n{server.log_tail()}"
    )


def start_server(
    workdir: Path,
    extra_args: list[str] | None = None,
    certs: dict[str, Path] | None = None,
    port: int | None = None,
    username: str = USERNAME,
    password: str | None = None,
    admin_cert_identity: str = ADMIN_CERT_IDENTITY,
) -> Server:
    """Start hardcharger-server on a free port, in ``workdir``, with an in-memory database.

    With ``certs`` (from :func:`make_certificates`) it serves TLS with that server certificate,
    verifies client certificates against the same CA (optional ones), and offers certificate
    sign-in, where ``admin_cert_identity`` signs in as the administrator. ``{base_url}`` in an
    extra argument becomes the server's own base URL (at 127.0.0.1).
    """
    binary = server_binary()
    port = port or free_port()
    scheme = "https" if certs is not None or "--tls-cert" in (extra_args or []) else "http"
    args = [arg.replace("{base_url}", f"{scheme}://127.0.0.1:{port}") for arg in extra_args or []]
    if certs is not None:
        args += [
            "--tls-cert",
            str(certs["cert"]),
            "--tls-key",
            str(certs["key"]),
            "--mtls-ca-cert",
            str(certs["ca"]),
            "--mtls-require-client-cert",
            "false",
            "--mtls-certificate-sign-in",
            "--mtls-admin-identities",
            admin_cert_identity,
        ]
    workdir.mkdir(parents=True, exist_ok=True)
    password = password or secrets.token_urlsafe(nbytes=12) + ":p@ss:word"
    log = workdir / "hardcharger-server.log"
    with log.open(mode="ab") as out:
        process = subprocess.Popen(
            args=[
                binary,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--health-port",
                "0",
                "--database",
                ":memory:",
                "--admin-username",
                username,
                # Every test expects UTC, whatever the machine's own zone (a time-zone bug would
                # otherwise pass by accident on a UTC machine).
                "--init-sql-commands",
                "SET TimeZone = 'UTC';",
                *args,
            ],
            env={**clean_environment(), "HARDCHARGER_ADMIN_PASSWORD": password},
            cwd=workdir,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    server = Server(
        host="127.0.0.1",
        port=port,
        password=password,
        process=process,
        log=log,
        tls=certs is not None or "--tls-cert" in args,
        ca=None if certs is None else certs["ca"],
        username=username,
    )
    _wait_up(server=server)
    return server


def stop_server(server: Server) -> None:
    if server.process.poll() is not None:
        return
    server.process.send_signal(signal.SIGTERM)
    server.process.send_signal(signal.SIGTERM)  # the second signal stops without draining
    try:
        server.process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        server.process.kill()


def make_certificates(out_dir: Path, admin_identity: str = ADMIN_CERT_IDENTITY) -> dict[str, Path]:
    """A throwaway CA; a server certificate for 127.0.0.1/localhost it signed; and client
    certificates ``admin`` (``admin_identity``) and ``stranger``
    (:data:`STRANGER_CERT_IDENTITY`), each with its key at ``paths[name + "-key"]``."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    def name(common_name: str) -> x509.Name:
        return x509.Name(attributes=[x509.NameAttribute(oid=NameOID.COMMON_NAME, value=common_name)])

    def pem_key(key) -> bytes:
        return key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    ca_key = ec.generate_private_key(curve=ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name=name(common_name="sqlframe-hardcharger test CA"))
        .issuer_name(name=name(common_name="sqlframe-hardcharger test CA"))
        .public_key(key=ca_key.public_key())
        .serial_number(number=x509.random_serial_number())
        .not_valid_before(time=now - datetime.timedelta(minutes=5))
        .not_valid_after(time=now + datetime.timedelta(days=1))
        .add_extension(extval=x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            extval=x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            extval=x509.SubjectKeyIdentifier.from_public_key(public_key=ca_key.public_key()),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    def leaf(common_name: str, san: list, usage) -> tuple:
        key = ec.generate_private_key(curve=ec.SECP256R1())
        cert = (
            x509.CertificateBuilder()
            .subject_name(name=name(common_name=common_name))
            .issuer_name(name=ca_cert.subject)
            .public_key(key=key.public_key())
            .serial_number(number=x509.random_serial_number())
            .not_valid_before(time=now - datetime.timedelta(minutes=5))
            .not_valid_after(time=now + datetime.timedelta(days=1))
            .add_extension(extval=x509.SubjectAlternativeName(general_names=san), critical=False)
            .add_extension(extval=x509.ExtendedKeyUsage(usages=[usage]), critical=False)
            .add_extension(
                extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key=ca_key.public_key()),
                critical=False,
            )
            .sign(private_key=ca_key, algorithm=hashes.SHA256())
        )
        return cert, key

    paths = {"ca": out_dir / "ca.pem"}
    paths["ca"].write_bytes(data=ca_cert.public_bytes(encoding=serialization.Encoding.PEM))
    leaves = {
        "cert": leaf(
            common_name="localhost",
            san=[x509.DNSName(value="localhost"), x509.IPAddress(value=ipaddress.ip_address(address="127.0.0.1"))],
            usage=ExtendedKeyUsageOID.SERVER_AUTH,
        ),
        "admin": leaf(
            common_name="admin",
            san=[x509.RFC822Name(value=admin_identity)],
            usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        ),
        "stranger": leaf(
            common_name="stranger",
            san=[x509.RFC822Name(value=STRANGER_CERT_IDENTITY)],
            usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        ),
    }
    for label, (cert, key) in leaves.items():
        key_label = "key" if label == "cert" else f"{label}-key"
        cert_path = out_dir / ("server.pem" if label == "cert" else f"{label}.pem")
        key_path = out_dir / ("server-key.pem" if label == "cert" else f"{label}-key.pem")
        cert_path.write_bytes(data=cert.public_bytes(encoding=serialization.Encoding.PEM))
        key_path.write_bytes(data=pem_key(key=key))
        paths[label] = cert_path
        paths[key_label] = key_path
    return paths
