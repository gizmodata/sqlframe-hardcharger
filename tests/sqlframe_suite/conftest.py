"""Fixtures for SQLFrame's engine suite (tests/sqlframe_suite/upstream, vendored by
scripts/vendor_sqlframe_suite.py) and the Hardcharger backend tests next to it.

Upstream parametrizes every test over its engines; here there is one, ``hardcharger``. Each test
gets its own HardchargerSession on a new connection (a new server session) to the shared test
server, after the server's database has been emptied, the way upstream's DuckDB tests each get a
fresh in-memory database.
"""

from __future__ import annotations

import os
import time
import typing as t
import warnings
from pathlib import Path

import adbc_driver_manager
import pyarrow.lib
import pytest
from _pytest.fixtures import FixtureRequest
from sqlframe.base.session import _BaseSession
from sqlframe.base.util import dialect_to_string
from sqlframe.base.util import get_func_from_session as get_func_from_session_without_fallback

from sqlframe_hardcharger import HardchargerDataFrame, HardchargerSession
from sqlframe_hardcharger import types as HardchargerTypes
from sqlframe_hardcharger.connect import HardchargerConnection

UPSTREAM = Path(__file__).resolve().parent / "upstream"

ENGINE_PARAMETERS = [pytest.param("hardcharger", marks=[pytest.mark.hardcharger])]

EmployeeData = t.List[t.Tuple[int, str, str, int, int]]
StoreData = t.List[t.Tuple[int, str, int, int]]
DistrictData = t.List[t.Tuple[int, str]]


def reset_database(cursor) -> None:
    """Drop everything the previous test left in the server's database ("memory")."""
    cursor.execute(
        "SELECT database_name FROM duckdb_databases() "
        "WHERE NOT internal AND database_name NOT IN ('memory', 'temp', 'system') "
        "AND NOT starts_with(database_name, '_hardcharger')"
    )
    for (name,) in cursor.fetchall():
        cursor.execute(f'DETACH DATABASE IF EXISTS "{name}"')
    cursor.execute("SELECT view_name, schema_name FROM duckdb_views() WHERE database_name = 'memory' AND NOT internal")
    for name, schema in cursor.fetchall():
        cursor.execute(f'DROP VIEW IF EXISTS memory."{schema}"."{name}" CASCADE')
    cursor.execute("SELECT table_name, schema_name FROM duckdb_tables() WHERE database_name = 'memory'")
    for name, schema in cursor.fetchall():
        cursor.execute(f'DROP TABLE IF EXISTS memory."{schema}"."{name}" CASCADE')
    cursor.execute(
        "SELECT function_name, schema_name, function_type FROM duckdb_functions() "
        "WHERE database_name = 'memory' AND NOT internal AND function_type IN ('macro', 'table_macro')"
    )
    for name, schema, kind in cursor.fetchall():
        table = " TABLE" if kind == "table_macro" else ""
        cursor.execute(f'DROP MACRO{table} IF EXISTS memory."{schema}"."{name}"')
    cursor.execute(
        "SELECT schema_name FROM duckdb_schemas() WHERE database_name = 'memory' AND NOT internal "
        "AND schema_name NOT IN ('main', 'information_schema', 'pg_catalog')"
    )
    for (name,) in cursor.fetchall():
        cursor.execute(f'DROP SCHEMA IF EXISTS memory."{name}" CASCADE')
    cursor.execute("USE memory.main")


# Upstream tests that can't pass here, each for a reason outside this package. strict: one that
# starts passing fails the run, so the list stays true; raises: it must fail the way described.
KNOWN_FAILURES: t.Dict[str, t.Tuple[str, t.Type[BaseException]]] = {
    "test_soundex": (
        "sqlframe's DuckDB functions run soundex as a Python UDF registered on an in-process DuckDB "
        "connection; a server can't call back into the client, and DuckDB has no soundex",
        adbc_driver_manager.ProgrammingError,
    ),
    "test_first_value": (
        "sqlframe 4.5.0 with pandas 3: a str column's missing values become NaN floats in "
        "createDataFrame()'s VALUES list; fails the same way on in-process DuckDB 1.5",
        adbc_driver_manager.ProgrammingError,
    ),
    "test_last_value": (
        "sqlframe 4.5.0 with pandas 3 (see test_first_value)",
        adbc_driver_manager.ProgrammingError,
    ),
    "test_explain": (
        "DuckDB 2.0 draws EXPLAIN plans differently (rounded boxes) from the DuckDB 1.x text upstream expects",
        AssertionError,
    ),
    "test_employee_extra_line_csv": (
        "the client-side CSV reader (as in sqlframe-gizmosql) parses with pyarrow and ignores, with a "
        "warning, DuckDB-only read_csv options (skip, null_padding, ignore_errors, auto_detect)",
        pyarrow.lib.ArrowInvalid,
    ),
    "test_employee_extra_line_csv_multiple": (
        "client-side CSV reader ignores DuckDB-only read_csv options (see test_employee_extra_line_csv)",
        pyarrow.lib.ArrowInvalid,
    ),
    "test_issue_219": (
        "the client-side CSV reader follows Spark (no header unless header=True, columns _c0, _c1, ...); "
        "sqlframe's DuckDB backend lets DuckDB's read_csv detect the header",
        adbc_driver_manager.ProgrammingError,
    ),
    "test_employee_delta": (
        "delta_scan needs DuckDB's delta extension, which the Hardcharger image doesn't ship "
        "(upstream skips this test in CI)",
        adbc_driver_manager.ProgrammingError,
    ),
}


# Upstream tests that pass or fail depending on the platform the server runs on: not strict, but
# when one fails it must fail the way described.
PLATFORM_DEPENDENT: t.Dict[str, t.Tuple[str, t.Type[BaseException]]] = {
    "test_array_distinct": (
        "DuckDB 2.0's list_distinct returns the distinct elements in hash order, which differs by "
        "platform: on macOS array_distinct([1, 2, 3, 2]) is [2, 3, 1], on Linux [1, 2, 3]; upstream "
        "accepts only [1, 2, 3] or [3, 2, 1]",
        AssertionError,
    ),
}


def pytest_collection_modifyitems(items):
    suite = Path(__file__).resolve().parent
    for item in items:
        if suite not in Path(item.path).resolve().parents:
            continue
        if item.originalname in KNOWN_FAILURES:
            reason, raises = KNOWN_FAILURES[item.originalname]
            item.add_marker(pytest.mark.xfail(reason=reason, raises=raises, strict=True))
        elif item.originalname in PLATFORM_DEPENDENT:
            reason, raises = PLATFORM_DEPENDENT[item.originalname]
            item.add_marker(pytest.mark.xfail(reason=reason, raises=raises, strict=False))


@pytest.fixture(autouse=True)
def run_in_upstream_dir(monkeypatch):
    """Upstream reads some fixture files by relative path (tests/fixtures/...)."""
    monkeypatch.chdir(UPSTREAM)


@pytest.fixture(scope="session", autouse=True)
def set_tz():
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    del os.environ["TZ"]


@pytest.fixture(scope="function", autouse=True)
def rescope_sparksession_singleton():
    _BaseSession._instance = None
    HardchargerSession.builder = HardchargerSession.Builder()
    yield


@pytest.fixture(scope="module", autouse=True)
def filter_warnings():
    warnings.filterwarnings("ignore", category=ResourceWarning)


@pytest.fixture
def hardcharger_connection(hc_connect_kwargs) -> t.Iterator[HardchargerConnection]:
    with HardchargerConnection(**hc_connect_kwargs) as conn:
        with conn.cursor() as cursor:
            reset_database(cursor=cursor)
            # Set the zone on this session explicitly rather than trusting the server's default
            # (CI's server reports 'Etc/UTC', the same zone under another name).
            cursor.execute("SET SESSION TimeZone = 'UTC'")
            cursor.execute("SELECT current_setting('TimeZone')")
            assert cursor.fetchone() == ("UTC",)
        yield conn


@pytest.fixture
def hardcharger_session(hardcharger_connection) -> HardchargerSession:
    return HardchargerSession(conn=hardcharger_connection)


@pytest.fixture(scope="module")
def _employee_data() -> EmployeeData:
    return [
        (1, "Jack", "Shephard", 37, 1),
        (2, "John", "Locke", 65, 1),
        (3, "Kate", "Austen", 37, 2),
        (4, "Claire", "Littleton", 27, 2),
        (5, "Hugo", "Reyes", 29, 100),
    ]


@pytest.fixture(scope="module")
def _store_data() -> StoreData:
    return [
        (1, "Hydra", 1, 37),
        (2, "Arrow", 2, 2000),
    ]


@pytest.fixture(scope="module")
def _district_data() -> DistrictData:
    return [
        (1, "Los Angeles"),
        (2, "Santa Monica"),
    ]


@pytest.fixture
def hardcharger_employee(hardcharger_session, _employee_data) -> HardchargerDataFrame:
    schema = HardchargerTypes.StructType(
        [
            HardchargerTypes.StructField("employee_id", HardchargerTypes.IntegerType(), False),
            HardchargerTypes.StructField("fname", HardchargerTypes.StringType(), False),
            HardchargerTypes.StructField("lname", HardchargerTypes.StringType(), False),
            HardchargerTypes.StructField("age", HardchargerTypes.IntegerType(), False),
            HardchargerTypes.StructField("store_id", HardchargerTypes.IntegerType(), False),
        ]
    )
    df = hardcharger_session.createDataFrame(data=_employee_data, schema=schema)
    df.createOrReplaceTempView("employee")
    return df


@pytest.fixture
def hardcharger_store(hardcharger_session, _store_data) -> HardchargerDataFrame:
    schema = HardchargerTypes.StructType(
        [
            HardchargerTypes.StructField("store_id", HardchargerTypes.IntegerType(), False),
            HardchargerTypes.StructField("store_name", HardchargerTypes.StringType(), False),
            HardchargerTypes.StructField("district_id", HardchargerTypes.IntegerType(), False),
            HardchargerTypes.StructField("num_sales", HardchargerTypes.IntegerType(), False),
        ]
    )
    df = hardcharger_session.createDataFrame(data=_store_data, schema=schema)
    df.createOrReplaceTempView("store")
    return df


@pytest.fixture
def hardcharger_district(hardcharger_session, _district_data) -> HardchargerDataFrame:
    schema = HardchargerTypes.StructType(
        [
            HardchargerTypes.StructField("district_id", HardchargerTypes.IntegerType(), False),
            HardchargerTypes.StructField("district_name", HardchargerTypes.StringType(), False),
        ]
    )
    df = hardcharger_session.createDataFrame(data=_district_data, schema=schema)
    df.createOrReplaceTempView("district")
    return df


def _engine_df_getter(request: FixtureRequest) -> t.Callable[[str], HardchargerDataFrame]:
    def _get(name: str) -> HardchargerDataFrame:
        return request.getfixturevalue(f"{request.param}_{name}")

    return _get


@pytest.fixture(params=ENGINE_PARAMETERS)
def get_engine_df(request: FixtureRequest) -> t.Callable[[str], HardchargerDataFrame]:
    return _engine_df_getter(request=request)


@pytest.fixture(params=ENGINE_PARAMETERS)
def get_df(request: FixtureRequest) -> t.Callable[[str], HardchargerDataFrame]:
    return _engine_df_getter(request=request)


@pytest.fixture(params=ENGINE_PARAMETERS)
def get_engine_df_and_pyspark(request: FixtureRequest) -> t.Callable[[str], HardchargerDataFrame]:
    return _engine_df_getter(request=request)


@pytest.fixture(params=ENGINE_PARAMETERS)
def get_session(request: FixtureRequest) -> t.Callable[[], HardchargerSession]:
    def _get() -> HardchargerSession:
        return request.getfixturevalue(f"{request.param}_session")

    return _get


@pytest.fixture(params=ENGINE_PARAMETERS)
def get_engine_session_and_spark(request: FixtureRequest) -> t.Callable[[], HardchargerSession]:
    def _get() -> HardchargerSession:
        return request.getfixturevalue(f"{request.param}_session")

    return _get


@pytest.fixture
def get_func() -> t.Callable[[str, _BaseSession], t.Callable]:
    def _get_func(name: str, session: _BaseSession) -> t.Callable:
        try:
            return get_func_from_session_without_fallback(name, session, fallback=False)
        except AttributeError:
            pytest.skip(f"{dialect_to_string(session.input_dialect)} does not support {name}")

    return _get_func


def _engine_is(name: str) -> t.Callable[[], bool]:
    return lambda: name == "duckdb"


# Hardcharger is DuckDB to the suite: its is_duckdb() checks hold, the other engines' don't.
@pytest.fixture
def is_duckdb() -> t.Callable[[], bool]:
    return _engine_is(name="duckdb")


@pytest.fixture
def is_standalone() -> t.Callable[[], bool]:
    return _engine_is(name="standalone")


@pytest.fixture
def is_postgres() -> t.Callable[[], bool]:
    return _engine_is(name="postgres")


@pytest.fixture
def is_bigquery() -> t.Callable[[], bool]:
    return _engine_is(name="bigquery")


@pytest.fixture
def is_redshift() -> t.Callable[[], bool]:
    return _engine_is(name="redshift")


@pytest.fixture
def is_snowflake() -> t.Callable[[], bool]:
    return _engine_is(name="snowflake")


@pytest.fixture
def is_spark() -> t.Callable[[], bool]:
    return _engine_is(name="spark")


@pytest.fixture
def is_databricks() -> t.Callable[[], bool]:
    return _engine_is(name="databricks")


@pytest.fixture
def fixture_root_path() -> str:
    """Upstream reads f"{fixture_root_path}/tests/fixtures/<file>"."""
    return str(UPSTREAM)


@pytest.fixture
def tmp_root_path() -> str:
    return ""
