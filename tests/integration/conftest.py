"""Fixtures for this package's own integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def session(hc_connect_kwargs):
    """A HardchargerSession built through the builder's hardcharger.* config keys."""
    from sqlframe_hardcharger import HardchargerSession

    builder = HardchargerSession.builder
    for name, value in hc_connect_kwargs.items():
        builder = builder.config(f"hardcharger.{name}", value)
    session = builder.getOrCreate()
    yield session
    session.stop()
