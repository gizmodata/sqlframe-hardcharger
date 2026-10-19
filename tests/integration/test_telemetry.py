"""OpenTelemetry: the driver (adbc-driver-hardcharger) traces every statement the session runs,
configured through the session builder's ``hardcharger.db_kwargs``."""

from __future__ import annotations

import pyarrow as pa
from sqlframe.base.session import _BaseSession


def test_statements_and_ingest_are_traced(session, hc_connect_kwargs, tmp_path):
    from sqlframe_hardcharger import HardchargerSession

    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    _BaseSession._instance = None
    try:
        builder = HardchargerSession.Builder()
        builder._session_kwargs.pop("conn", None)
        builder._hardcharger_connect_kwargs.clear()  # after activate(), builders start from its config
        for name, value in hc_connect_kwargs.items():
            builder = builder.config(f"hardcharger.{name}", value)
        traced = builder.config(
            "hardcharger.db_kwargs",
            {
                "adbc.telemetry.traces_exporter": "adbcfile",
                "adbc.telemetry.traces_folder_path": str(traces_dir),
            },
        ).getOrCreate()
        assert traced.sql("SELECT 42 AS answer").collect()[0].answer == 42
        traced.ingest(table_name="traced_ingest", data=pa.table(data={"id": [1, 2, 3]}), mode="replace")
        traced._conn.close()
    finally:
        _BaseSession._instance = session

    contents = "".join(path.read_text() for path in traces_dir.iterdir())
    assert "Database.Open" in contents
    assert "Statement.ExecuteQuery" in contents
    assert "Statement.ExecuteUpdate" in contents
