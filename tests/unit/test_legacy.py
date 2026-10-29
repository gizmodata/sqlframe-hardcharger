"""Statement options reach a driver from before the protocol's rename under their old names."""

from unittest.mock import MagicMock

import pytest
from adbc_driver_manager import NotSupportedError

from sqlframe_hardcharger._legacy import legacy_statement_options
from sqlframe_hardcharger.connect import HardchargerAdbcCursor


def refusing_current_names() -> MagicMock:
    """A driver statement that knows its options only by the old names, as
    adbc-driver-hardcharger 2.0.2 does."""
    statement = MagicMock()

    def set_options(**options):
        if any(key.startswith("adbc.chargewire.") for key in options):
            raise NotSupportedError("NOT_IMPLEMENTED: Unknown statement option")

    statement.set_options.side_effect = set_options
    return statement


def test_legacy_statement_options():
    assert legacy_statement_options(options={"adbc.chargewire.ingest.parts": "1", "other": "x"}) == {
        "adbc.warp.ingest.parts": "1",
        "other": "x",
    }
    assert legacy_statement_options(options={"adbc.hardcharger.query_tag": "{}"}) is None


def test_options_retry_under_the_old_names():
    inner = MagicMock()
    inner.adbc_statement = refusing_current_names()
    cursor = HardchargerAdbcCursor(parent=MagicMock(), inner=inner)
    cursor.set_statement_options(options={"adbc.chargewire.ingest.parts": "1"})

    assert inner.adbc_statement.set_options.call_args_list[-1].kwargs == {"adbc.warp.ingest.parts": "1"}


def test_other_refusals_are_not_retried():
    inner = MagicMock()
    inner.adbc_statement = refusing_current_names()
    inner.adbc_statement.set_options.side_effect = NotSupportedError("NOT_IMPLEMENTED: Unknown statement option")
    cursor = HardchargerAdbcCursor(parent=MagicMock(), inner=inner)
    with pytest.raises(NotSupportedError):
        cursor.set_statement_options(options={"adbc.hardcharger.unknown": "1"})
    assert inner.adbc_statement.set_options.call_count == 1
