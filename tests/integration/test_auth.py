"""Sign-in and transport through the session builder: TLS (verified, skipped, plain HTTP),
password, access token, client certificate (mTLS) and the server's browser (OAuth) sign-in.
Every refusal asserts why it was refused, next to a twin that succeeds."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
from sqlframe.base.session import _BaseSession

from tests.hardcharger_server import (
    ADMIN_CERT_IDENTITY,
    USERNAME,
    start_server,
    stop_server,
)

OAUTH_DIR = pathlib.Path(__file__).resolve().parent.parent / "oauth"
AUDIENCE = "sqlframe-hardcharger-test"
CLIENT_ID = "sqlframe-hardcharger-client"
CLIENT_SECRET = "sqlframe-hardcharger-secret"
IDP_EMAIL = "analyst@gizmodata.com"


@pytest.fixture
def make_session(session):
    """Build brand-new sessions from ``hardcharger.*`` config keys; afterwards the shared session
    is the process singleton again."""
    from sqlframe_hardcharger import HardchargerSession

    built = []

    def _make(**connect_kwargs):
        _BaseSession._instance = None
        builder = HardchargerSession.Builder()
        builder._session_kwargs.pop("conn", None)
        builder._hardcharger_connect_kwargs.clear()
        for name, value in connect_kwargs.items():
            builder = builder.config(f"hardcharger.{name}", value)
        new_session = builder.getOrCreate()
        built.append(new_session)
        return new_session

    yield _make
    for new_session in built:
        new_session._conn.close()
    _BaseSession._instance = session


def current_user(session) -> str:
    return session.sql("SELECT HARDCHARGER_USER() AS user_name").collect()[0].user_name


def auth_method(session) -> str:
    cursor = session._cur
    cursor.execute("SELECT auth_method FROM hardcharger_sessions() WHERE is_current")
    return cursor.fetchone()[0]


class TestTls:
    def test_password_over_verified_tls(self, make_session, hc_server):
        session = make_session(
            uri=hc_server.uri, username=USERNAME, password=hc_server.password, tls_root_certs=str(hc_server.ca)
        )
        assert hc_server.uri.startswith("hardcharger://") and "tls=false" not in hc_server.uri
        assert current_user(session=session) == USERNAME
        assert auth_method(session=session) == "password"

    def test_unknown_ca_is_refused(self, make_session, hc_server):
        """TLS is verified by default: a server whose CA the client doesn't trust is refused."""
        with pytest.raises(Exception) as excinfo:
            make_session(uri=hc_server.uri, username=USERNAME, password=hc_server.password)
        # Go's wording: Linux (CI), macOS.
        reasons = ("certificate signed by unknown authority", "certificate is not trusted")
        assert any(reason in str(excinfo.value) for reason in reasons), str(excinfo.value)

    def test_tls_skip_verify(self, make_session, hc_server):
        session = make_session(uri=hc_server.uri, username=USERNAME, password=hc_server.password, tls_skip_verify=True)
        assert current_user(session=session) == USERNAME

    def test_plain_http_server(self, make_session, tmp_path):
        server = start_server(workdir=tmp_path)
        try:
            session = make_session(uri=server.uri, username=USERNAME, password=server.password)
            assert server.uri.endswith("?tls=false")
            assert current_user(session=session) == USERNAME
            # Before the server stops: closing a connection whose server is gone fails (the
            # driver can't end the server session) and leaks the driver's handles.
            session._conn.close()
        finally:
            stop_server(server=server)


class TestPasswordAndToken:
    def test_wrong_password_is_refused(self, make_session, hc_server):
        with pytest.raises(Exception) as excinfo:
            make_session(
                uri=hc_server.uri, username=USERNAME, password="not-the-password", tls_root_certs=str(hc_server.ca)
            )
        assert "invalid_credentials" in str(excinfo.value)

    def test_access_token(self, make_session, hc_server):
        session = make_session(
            uri=hc_server.uri, access_token=hc_server.password_token(), tls_root_certs=str(hc_server.ca)
        )
        assert current_user(session=session) == USERNAME

    def test_forged_access_token_is_refused(self, make_session, hc_server):
        with pytest.raises(Exception) as excinfo:
            make_session(uri=hc_server.uri, access_token="not-a-token", tls_root_certs=str(hc_server.ca))
        assert "invalid_token" in str(excinfo.value)


class TestClientCertificate:
    def test_client_certificate_sign_in(self, make_session, hc_server, hc_certs):
        session = make_session(
            uri=hc_server.uri,
            auth_type="client_certificate",
            tls_root_certs=str(hc_certs["ca"]),
            tls_client_cert=str(hc_certs["admin"]),
            tls_client_key=str(hc_certs["admin-key"]),
        )
        assert current_user(session=session).lower() == ADMIN_CERT_IDENTITY
        assert auth_method(session=session) == "client_certificate"
        # Bulk ingest's parallel parts each present the certificate the token is bound to.
        import pyarrow as pa

        df = session.ingest(
            table_name="certificate_ingest",
            data=pa.table(data={"k": list(range(100_000))}),
            mode="replace",
        )
        assert df.count() == 100_000

    def test_unknown_certificate_identity_is_refused(self, make_session, hc_server, hc_certs):
        with pytest.raises(Exception) as excinfo:
            make_session(
                uri=hc_server.uri,
                auth_type="client_certificate",
                tls_root_certs=str(hc_certs["ca"]),
                tls_client_cert=str(hc_certs["stranger"]),
                tls_client_key=str(hc_certs["stranger-key"]),
            )
        assert "unknown_certificate_identity" in str(excinfo.value)

    def test_activate_with_client_certificate(self, session, hc_server, hc_certs):
        from sqlframe_hardcharger import activate

        activate(
            uri=hc_server.uri,
            auth_type="client_certificate",
            tls_root_certs=str(hc_certs["ca"]),
            tls_client_cert=str(hc_certs["admin"]),
            tls_client_key=str(hc_certs["admin-key"]),
        )
        from pyspark.sql import SparkSession

        _BaseSession._instance = None
        try:
            spark = SparkSession.builder.getOrCreate()
            assert current_user(session=spark).lower() == ADMIN_CERT_IDENTITY
            spark._conn.close()
        finally:
            _BaseSession._instance = session


@pytest.fixture(scope="module")
def idp_issuer():
    """The mock identity provider, in its own process (see tests/oauth/mock_idp.py)."""
    process = subprocess.Popen(
        args=[sys.executable, str(OAUTH_DIR / "mock_idp.py"), AUDIENCE, CLIENT_ID, CLIENT_SECRET],
        stdout=subprocess.PIPE,
        text=True,
    )
    issuer = process.stdout.readline().strip()
    if not issuer.startswith("http://127.0.0.1:"):
        process.kill()
        pytest.fail(reason=f"the mock identity provider did not start: {issuer!r}")
    yield issuer
    process.kill()
    process.wait()


@pytest.fixture(scope="module")
def oauth_server(tmp_path_factory, idp_issuer):
    server = start_server(
        workdir=tmp_path_factory.mktemp("oauth"),
        extra_args=[
            "--token-allowed-issuer",
            idp_issuer,
            "--token-allowed-audience",
            AUDIENCE,
            "--token-default-role",
            "admin",
            "--token-authorized-emails",
            "*@gizmodata.com",
            "--oauth-client-id",
            CLIENT_ID,
            "--oauth-client-secret",
            CLIENT_SECRET,
            # Browser sign-in runs on the server's own port (Warp SQL §4.3); the redirect URI
            # names 127.0.0.1, where the tests dial it.
            "--oauth-base-url",
            "{base_url}",
        ],
    )
    yield server
    stop_server(server=server)


def fake_browser(code: str) -> str:
    """The command the driver opens the sign-in URL with: the identity provider sends it back to the
    server's callback with ``code``."""
    return f"{sys.executable} {OAUTH_DIR / 'fake_browser.py'} {code}"


class TestBrowserSignIn:
    def test_browser_sign_in(self, make_session, oauth_server):
        session = make_session(
            uri=oauth_server.uri,
            auth_type="external",
            open_browser=fake_browser(code="code-ok"),
            oauth_timeout=30,
        )
        assert current_user(session=session) == IDP_EMAIL
        assert session.sql("SELECT 1 AS one").collect()[0].one == 1

    def test_browser_sign_in_with_a_rejected_code(self, make_session, oauth_server):
        with pytest.raises(Exception) as excinfo:
            make_session(
                uri=oauth_server.uri,
                auth_type="external",
                open_browser=fake_browser(code="code-bad"),
                oauth_timeout=30,
            )
        assert "invalid_grant" in str(excinfo.value)
