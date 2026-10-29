# Vendored from eakmanrq/sqlframe v4.9.0 (34f250a) tests/integration/engines/duck/test_duckdb_reader.py by
# scripts/vendor_sqlframe_suite.py: mechanical rewrites only (see that script). Don't edit;
# re-run the script. Upstream license: MIT.
import os

import pytest

from sqlframe.base.types import Row
from tests.sqlframe_suite.compat import DuckDBSession
from tests.sqlframe_suite.compat import functions as F



def test_employee_extra_line_csv(hardcharger_session: DuckDBSession):
    df = hardcharger_session.read.load(
        "tests/fixtures/employee_extra_line.csv",
        format="csv",
        schema="employee_id INT, fname STRING, lname STRING, age INT, store_id INT",
        skip=1,
        header=1,
        filename=1,
        null_padding=True,
        ignore_errors=1,
        auto_detect=False,
        sep=",",
    )
    assert df.collect() == [
        Row(
            **{
                "employee_id": 1,
                "fname": "Jack",
                "lname": "Shephard",
                "age": 37,
                "store_id": 1,
                "filename": "tests/fixtures/employee_extra_line.csv",
            }
        ),
        Row(
            **{
                "employee_id": 2,
                "fname": "John",
                "lname": "Locke",
                "age": 65,
                "store_id": 1,
                "filename": "tests/fixtures/employee_extra_line.csv",
            }
        ),
        Row(
            **{
                "employee_id": 3,
                "fname": "Kate",
                "lname": "Austen",
                "age": 37,
                "store_id": 2,
                "filename": "tests/fixtures/employee_extra_line.csv",
            }
        ),
        Row(
            **{
                "employee_id": 4,
                "fname": "Claire",
                "lname": "Littleton",
                "age": 27,
                "store_id": 2,
                "filename": "tests/fixtures/employee_extra_line.csv",
            }
        ),
        Row(
            **{
                "employee_id": 5,
                "fname": "Hugo",
                "lname": "Reyes",
                "age": 29,
                "store_id": 100,
                "filename": "tests/fixtures/employee_extra_line.csv",
            }
        ),
    ]


def test_employee_extra_line_csv_multiple(hardcharger_session: DuckDBSession):
    df = hardcharger_session.read.load(
        ["tests/fixtures/employee_extra_line.csv", "tests/fixtures/employee_extra_line.csv"],
        format="csv",
        schema="employee_id INT, fname STRING, lname STRING, age INT, store_id INT",
        skip=1,
        header=1,
        filename=0,
        null_padding=True,
        ignore_errors=1,
        auto_detect=False,
    )
    assert df.collect() == [
        Row(**{"employee_id": 1, "fname": "Jack", "lname": "Shephard", "age": 37, "store_id": 1}),
        Row(**{"employee_id": 2, "fname": "John", "lname": "Locke", "age": 65, "store_id": 1}),
        Row(**{"employee_id": 3, "fname": "Kate", "lname": "Austen", "age": 37, "store_id": 2}),
        Row(
            **{"employee_id": 4, "fname": "Claire", "lname": "Littleton", "age": 27, "store_id": 2}
        ),
        Row(**{"employee_id": 5, "fname": "Hugo", "lname": "Reyes", "age": 29, "store_id": 100}),
        Row(**{"employee_id": 1, "fname": "Jack", "lname": "Shephard", "age": 37, "store_id": 1}),
        Row(**{"employee_id": 2, "fname": "John", "lname": "Locke", "age": 65, "store_id": 1}),
        Row(**{"employee_id": 3, "fname": "Kate", "lname": "Austen", "age": 37, "store_id": 2}),
        Row(
            **{"employee_id": 4, "fname": "Claire", "lname": "Littleton", "age": 27, "store_id": 2}
        ),
        Row(**{"employee_id": 5, "fname": "Hugo", "lname": "Reyes", "age": 29, "store_id": 100}),
    ]


def test_employee_delta(hardcharger_session: DuckDBSession):
    if os.environ.get("CI"):
        pytest.skip(
            "DuckDB Delta is not working in CI with DuckDB 1.2.1. Error: `duckdb.duckdb.Error: An error occurred while trying to automatically install the required extension 'delta'`"
        )
    df = hardcharger_session.read.load(
        "tests/fixtures/employee_delta",
        format="delta",
    )
    assert df.collect() == [
        Row(**{"employee_id": 1, "fname": "Jack", "lname": "Shephard", "age": 37, "store_id": 1}),
        Row(**{"employee_id": 2, "fname": "John", "lname": "Locke", "age": 65, "store_id": 1}),
        Row(**{"employee_id": 3, "fname": "Kate", "lname": "Austen", "age": 37, "store_id": 2}),
        Row(
            **{"employee_id": 4, "fname": "Claire", "lname": "Littleton", "age": 27, "store_id": 2}
        ),
        Row(**{"employee_id": 5, "fname": "Hugo", "lname": "Reyes", "age": 29, "store_id": 100}),
    ]


def test_issue_219(hardcharger_session: DuckDBSession):
    df1 = hardcharger_session.read.csv("tests/fixtures/issue_219.csv")
    df2 = df1.groupBy("kind", "make").agg(F.min("price"))
    # Just making sure this doesn't raise like it did before
    df2.show()

    # 222
    lightbulbs = hardcharger_session.read.csv("tests/fixtures/issue_219.csv")
    min_prices = lightbulbs.groupBy("kind", "make").agg(F.min("price"))
    lightbulbs.join(min_prices, "make").show()


# https://github.com/eakmanrq/sqlframe/issues/242
def test_read_parquet_optimize(hardcharger_session: DuckDBSession):
    df = hardcharger_session.read.parquet(
        "tests/fixtures/employee.parquet"
    )  # Contains a `person_id` and a `person_source_value` column
    df.createOrReplaceTempView("employee")
    hardcharger_session.table("employee").sql(optimize=True)


# https://github.com/eakmanrq/sqlframe/issues/382
def test_read_parquet_preserves_column_case(hardcharger_session: DuckDBSession, tmp_path):
    path = tmp_path / "mixed_case.parquet"
    hardcharger_session._conn.execute(
        f"""COPY (SELECT 1 AS "UPPER_NAME", 2 AS "MixedCase", 3 AS lower_name)
            TO '{path}' (FORMAT PARQUET)"""
    )

    df = hardcharger_session.read.parquet(str(path))

    assert df.columns == ["UPPER_NAME", "MixedCase", "lower_name"]
    assert [field.name for field in df.schema.fields] == df.columns
    assert df.collect()[0].asDict() == {"UPPER_NAME": 1, "MixedCase": 2, "lower_name": 3}
    assert df.select("*").columns == df.columns
    assert df.filter("upper_name = 1").columns == df.columns
    assert df.select("upper_name", "MIXEDCASE").collect()[0] == (1, 2)


# https://github.com/eakmanrq/sqlframe/issues/499
def test_quoted_columns_parquet(hardcharger_session: DuckDBSession):
    df = hardcharger_session.read.parquet("tests/fixtures/netflix_daily_top_10.parquet")
    df = (
        df.filter(F.col("Type") == "TV Show")
        .groupBy("Title")
        .agg(F.max(F.col("Days In Top 10")).alias("max_days_in_top_10"))
        .orderBy(F.desc("max_days_in_top_10"))
        .limit(4)
    )
    assert df.collect() == [
        Row(**{"Title": "Cocomelon", "max_days_in_top_10": 428}),
        Row(**{"Title": "Ozark", "max_days_in_top_10": 89}),
        Row(**{"Title": "Cobra Kai", "max_days_in_top_10": 81}),
        Row(**{"Title": "Manifest", "max_days_in_top_10": 80}),
    ]
