"""Unit tests for the connect module."""

from unittest.mock import MagicMock


def test_connection_has_required_methods():
    from sqlframe_hardcharger.connect import HardchargerConnection

    for name in ("cursor", "close", "commit", "rollback", "__enter__", "__exit__"):
        assert hasattr(HardchargerConnection, name)


def test_cursor_proxies_the_methods_sqlframe_and_ingest_use():
    from sqlframe_hardcharger.connect import HardchargerAdbcCursor

    for name in ("execute", "fetchone", "fetchall", "fetchmany", "fetch_arrow_table", "adbc_ingest"):
        assert hasattr(HardchargerAdbcCursor, name)


def test_cursor_close_is_idempotent_and_unregisters():
    from sqlframe_hardcharger.connect import HardchargerAdbcCursor

    parent = MagicMock()
    inner = MagicMock()
    cursor = HardchargerAdbcCursor(parent=parent, inner=inner)
    cursor.close()
    cursor.close()

    inner.close.assert_called_once_with()
    parent._unregister_cursor.assert_called_once_with(cursor=cursor)
    assert cursor.description is None


def test_closed_cursor_refuses_work():
    import pytest

    from sqlframe_hardcharger.connect import HardchargerAdbcCursor

    cursor = HardchargerAdbcCursor(parent=MagicMock(), inner=MagicMock())
    cursor.close()
    with pytest.raises(RuntimeError, match="closed"):
        cursor.execute("SELECT 1")


def test_statement_options_reach_the_driver_statement():
    from sqlframe_hardcharger.connect import HardchargerAdbcCursor

    inner = MagicMock()
    cursor = HardchargerAdbcCursor(parent=MagicMock(), inner=inner)
    cursor.set_statement_options(options={"hardcharger.ingest.parts": "1"})

    inner.adbc_statement.set_options.assert_called_once_with(**{"hardcharger.ingest.parts": "1"})


def test_the_ingest_option_is_the_drivers_current_name():
    """adbc-driver-hardcharger 2.7.0's name, set once per ingest statement: the driver prints no
    deprecation line, and no second spelling of it is ever sent beside it."""
    from adbc_driver_hardcharger import StatementOptions, _legacy

    from sqlframe_hardcharger.session import INGEST_PARTS_OPTION

    assert INGEST_PARTS_OPTION == StatementOptions.INGEST_PARTS.value == "hardcharger.ingest.parts"
    assert _legacy.current_key(key=INGEST_PARTS_OPTION) == (INGEST_PARTS_OPTION, 0)
