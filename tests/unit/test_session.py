"""Unit tests for HardchargerSession.Builder and activate() configuration."""

from unittest.mock import patch

import pytest


def _build(configure) -> dict:
    """Run the builder with a fake connection; return its connect() kwargs."""
    from sqlframe_hardcharger.session import HardchargerSession

    captured: dict = {}

    class FakeConnection:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    # Also stub HardchargerSession itself: the real class is a process-wide
    # singleton (`_BaseSession._instance`), and letting `builder.session`
    # construct one for real here would leak into every other test in this
    # pytest process that expects a genuinely server-connected session.
    with (
        patch("sqlframe_hardcharger.connect.HardchargerConnection", FakeConnection),
        patch("sqlframe_hardcharger.session.HardchargerSession", lambda **kwargs: None),
    ):
        builder = HardchargerSession.Builder()
        # activate() (run by other tests in the same process) swaps
        # HardchargerSession.Builder for one that starts from its config.
        builder._session_kwargs.pop("conn", None)
        builder._hardcharger_connect_kwargs.clear()
        configure(builder)
        builder.session  # noqa: B018 - triggers connection construction
    return captured


def test_config_keys_become_connect_kwargs():
    captured = _build(
        configure=lambda builder: (
            builder.config("hardcharger.uri", "hardcharger://db.example.com")
            .config("hardcharger.username", "analyst")
            .config("hardcharger.password", "secret")
            .config("hardcharger.tls_root_certs", "/etc/ca.pem")
            .config("hardcharger.query_tag", {"job": "nightly"})
        )
    )
    assert captured == {
        "uri": "hardcharger://db.example.com",
        "username": "analyst",
        "password": "secret",
        "tls_root_certs": "/etc/ca.pem",
        "query_tag": {"job": "nightly"},
    }


def test_config_map_takes_hardcharger_keys():
    captured = _build(
        configure=lambda builder: builder.config(
            map={
                "hardcharger.uri": "hardcharger://db.example.com",
                "hardcharger.access_token": "tok",
                "sqlframe.input.dialect": "spark",
            }
        )
    )
    assert captured == {"uri": "hardcharger://db.example.com", "access_token": "tok"}


@pytest.mark.parametrize(
    argnames=("value", "expected"),
    argvalues=[(True, True), ("true", True), ("1", True), (False, False), ("false", False)],
)
def test_tls_skip_verify_is_a_boolean(value, expected):
    captured = _build(
        configure=lambda builder: builder.config("hardcharger.uri", "hardcharger://h").config(
            "hardcharger.tls_skip_verify", value
        )
    )
    assert captured["tls_skip_verify"] is expected


def test_client_certificate_and_oauth_options_pass_through():
    captured = _build(
        configure=lambda builder: (
            builder.config("hardcharger.uri", "hardcharger://h")
            .config("hardcharger.auth_type", "client_certificate")
            .config("hardcharger.tls_client_cert", "client.pem")
            .config("hardcharger.tls_client_key", "client-key.pem")
            .config("hardcharger.oauth_timeout", "30")
        )
    )
    assert captured == {
        "uri": "hardcharger://h",
        "auth_type": "client_certificate",
        "tls_client_cert": "client.pem",
        "tls_client_key": "client-key.pem",
        "oauth_timeout": 30.0,
    }


def test_unknown_hardcharger_key_is_refused():
    from sqlframe_hardcharger.session import HardchargerSession

    builder = HardchargerSession.Builder()
    with pytest.raises(ValueError, match="unknown Hardcharger config key 'hardcharger.max_msg_size'"):
        builder.config("hardcharger.max_msg_size", 1)


def test_no_uri_means_no_connection():
    captured = _build(configure=lambda builder: builder.config("hardcharger.username", "analyst"))
    assert captured == {}


def test_activate_refuses_unknown_keyword():
    from sqlframe_hardcharger import activate

    with pytest.raises(TypeError, match="max_msg_size"):
        activate(uri="hardcharger://h", max_msg_size=1)
