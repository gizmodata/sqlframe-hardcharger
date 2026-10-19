"""SQLFrame's DuckDB backend tests that need more than a fixture rename to run on Hardcharger,
ported by hand from eakmanrq/sqlframe v4.5.0 tests/integration/engines/duck/:
test_duckdb_session.py, test_duckdb_udf.py and test_duckdb_activate.py.

Not ported: test_tpcds.py, which compares each TPC-DS query's result with a PySpark session's on
a JVM."""

from __future__ import annotations

import pytest
from sqlglot import exp

from sqlframe_hardcharger import HardchargerSession
from sqlframe_hardcharger import functions as F
from sqlframe_hardcharger.connect import HardchargerConnection
from sqlframe_hardcharger.types import Row


@pytest.mark.parametrize(argnames="value", argvalues=[float("inf"), float("-inf")])
def test_float_infinity_literals(hardcharger_session, value):
    session = hardcharger_session
    df = session.createDataFrame(data=[(value,), (1.0,)], schema=["a"])
    assert df.select(
        (F.col("a") == value).alias("equal"),
        F.col("a").isin([value, 2.0]).alias("member"),
        F.lit([value, 1.0]).alias("array"),
    ).collect() == [
        Row(equal=True, member=True, array=[value, 1.0]),
        Row(equal=False, member=False, array=[value, 1.0]),
    ]
    assert session.createDataFrame(data=[([value, 1.0],)], schema=["a"]).collect() == [Row(a=[value, 1.0])]


def test_session_from_config(hardcharger_connection):
    with hardcharger_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE test_table (cola INT, colb STRING)")
    session = HardchargerSession.builder.config("sqlframe.conn", hardcharger_connection).getOrCreate()
    columns = session.catalog.get_columns("test_table")
    assert columns == {"cola": exp.DataType.build("INT"), "colb": exp.DataType.build("TEXT")}
    assert session.execution_dialect_name == "duckdb"


def test_session_from_hardcharger_config(hc_connect_kwargs):
    builder = HardchargerSession.builder
    for name, value in hc_connect_kwargs.items():
        builder = builder.config(f"hardcharger.{name}", value)
    session = builder.getOrCreate()
    try:
        assert session.range(1, 2).collect() == [Row(id=1)]
        assert session.execution_dialect_name == "duckdb"
    finally:
        session.stop()


def test_session_input_dialect_from_config(hardcharger_connection):
    """Upstream's test_activate_with_connection_and_input_dialect, through the builder."""
    with hardcharger_connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA "memory"."activate_test"')
        cursor.execute('CREATE TABLE "memory"."activate_test"."test" (a INT)')
        cursor.execute('INSERT INTO "memory"."activate_test"."test" VALUES (1)')
    session = (
        HardchargerSession.builder.config("sqlframe.conn", hardcharger_connection)
        .config("sqlframe.input.dialect", "duckdb")
        .getOrCreate()
    )
    assert session.table("memory.activate_test.test").select('"a"').collect() == [(1,)]


def test_session_stop(hardcharger_session):
    """After stop() the session's connection is closed (upstream: DuckDB's ConnectionException)."""
    assert hardcharger_session.range(1, 2).collect() == [Row(id=1)]
    hardcharger_session.stop()
    with pytest.raises(RuntimeError, match="closed"):
        hardcharger_session.range(1, 10).collect()


def test_session_new_session(hardcharger_session, hc_connect_kwargs):
    assert hardcharger_session.range(1, 2).collect() == [Row(id=1)]
    hardcharger_session.stop()
    new_session = HardchargerSession.builder.config("sqlframe.conn", HardchargerConnection(**hc_connect_kwargs))
    new_session = new_session.getOrCreate()
    try:
        assert new_session is not hardcharger_session
        assert isinstance(new_session, HardchargerSession)
        assert new_session.range(1, 2).collect() == [Row(id=1)]
    finally:
        new_session.stop()


def test_udf_register_is_refused(hardcharger_session):
    """Upstream registers a Python UDF on the in-process DuckDB connection; a Hardcharger server
    can't call back into this Python process, so registering one says so."""

    def multi(x: int, y: int) -> int:
        return x * y

    with pytest.raises(NotImplementedError, match="Python UDFs are not supported on Hardcharger"):
        hardcharger_session.udf.register("multi", multi)


def test_activate_with_connection(hardcharger_connection):
    from sqlframe_hardcharger import activate

    with hardcharger_connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA "memory"."activate_test"')
        cursor.execute('CREATE TABLE "memory"."activate_test"."test" (a INT)')
        cursor.execute('INSERT INTO "memory"."activate_test"."test" VALUES (1)')
    activate(conn=hardcharger_connection)
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("test").getOrCreate()
    df = spark.table("memory.activate_test.test").select("`a`")
    assert df.collect() == [(1,)]
