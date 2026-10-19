"""Shared fixtures: one real hardcharger-server per test run (see tests/hardcharger_server.py),
serving TLS with a throwaway CA that the client verifies. Only the tests that ask for it start
it; the unit tests never do."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.hardcharger_server import make_certificates, start_server, stop_server

UNIT_TESTS = Path(__file__).resolve().parent / "unit"


def pytest_collection_modifyitems(items):
    """Everything outside tests/unit runs against a live server: mark it ``integration``."""
    for item in items:
        if UNIT_TESTS not in Path(item.path).resolve().parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def hc_certs(tmp_path_factory):
    return make_certificates(out_dir=tmp_path_factory.mktemp("certs"))


@pytest.fixture(scope="session")
def hc_server(tmp_path_factory, hc_certs):
    """A TLS server (with optional client certificates and certificate sign-in)."""
    server = start_server(workdir=tmp_path_factory.mktemp("server"), certs=hc_certs)
    yield server
    stop_server(server=server)


@pytest.fixture(scope="session")
def hc_connect_kwargs(hc_server) -> dict:
    """connect() keyword arguments for the admin user: URI, credentials and the CA to trust."""
    return hc_server.connect_kwargs()
