#!/usr/bin/env python3
"""Vendor SQLFrame's engine test suite into tests/sqlframe_suite/upstream.

SQLFrame (eakmanrq/sqlframe) tests every backend with the same engine-agnostic suite
(tests/integration/engines/test_*.py), parametrized over engines. This copies that suite at a
pinned release, with mechanical rewrites only, so it runs against Hardcharger:

- the DuckDB backend's names (``DuckDBSession``, ``DuckDBCatalog``, ...) are imported from
  tests/sqlframe_suite/compat.py, which binds them to the Hardcharger classes: Hardcharger runs
  DuckDB, so every "if DuckDB" branch of the suite (expected values, skips) applies to it;
- ``pyspark`` imports, and ``DatabricksSession`` (whose module needs the Databricks connector to
  import), become stand-ins from compat.py: the suite only uses them for ``isinstance`` checks
  against sessions that never exist here;
- ``pytest_plugins`` lines go (tests/sqlframe_suite/conftest.py provides the fixtures);
- the DuckDB backend's own catalog, DataFrame and reader tests come along, renamed
  test_backend_*.py, with their ``duckdb_*`` fixtures renamed ``hardcharger_*``;
- the data files the suite reads (tests/fixtures/) are copied too.

Usage: scripts/vendor_sqlframe_suite.py [--ref v4.5.0] [--source DIR]
Without --source it shallow-clones https://github.com/eakmanrq/sqlframe at --ref.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile

REPO = "https://github.com/eakmanrq/sqlframe.git"
DEFAULT_REF = "v4.5.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "tests" / "sqlframe_suite" / "upstream"
SUITE_FILES = [
    "test_engine_column.py",
    "test_engine_dataframe.py",
    "test_engine_reader.py",
    "test_engine_session.py",
    "test_engine_table.py",
    "test_engine_writer.py",
    "test_int_functions.py",
    "test_int_testing.py",
]
# The DuckDB backend's own tests (tests/integration/engines/duck/), which apply to Hardcharger as
# written once their fixtures are the Hardcharger ones. The rest of that directory is ported by
# hand (tests/sqlframe_suite/test_hardcharger_backend.py) or not at all (test_tpcds.py compares
# with a PySpark session on a JVM).
BACKEND_FILES = {
    "test_duckdb_catalog.py": "test_backend_catalog.py",
    "test_duckdb_dataframe.py": "test_backend_dataframe.py",
    "test_duckdb_reader.py": "test_backend_reader.py",
}
FIXTURE_FILES = [
    "employee.csv",
    "employee.json",
    "employee.parquet",
    "employee_extra_line.csv",
    "issue_219.csv",
    "netflix_daily_top_10.parquet",
]
FIXTURE_DIRS = ["employee_delta"]

# test_duckdb_catalog.py builds its session on an in-process DuckDB connection.
CATALOG_FIXTURE_OLD = """def duckdb_session() -> DuckDBSession:
    import duckdb

    connector = duckdb.connect()
    connector.execute("set TimeZone = 'UTC'")
    connector.execute("SELECT * FROM duckdb_settings() WHERE name = 'TimeZone'")
    assert connector.fetchone()[1] == "UTC"  # type: ignore
    session = DuckDBSession(connector)
"""
CATALOG_FIXTURE_NEW = """def duckdb_session(hardcharger_connection) -> DuckDBSession:
    session = DuckDBSession(hardcharger_connection)
"""

REWRITES: list[tuple[str, str]] = [
    (r"^pytest_plugins = .*\n", ""),
    (
        r"^from pyspark\.sql import SparkSession as PySparkSession$",
        "from tests.sqlframe_suite.compat import PySparkSession",
    ),
    (
        r"^from pyspark\.errors\.exceptions\.captured import AnalysisException$",
        "from tests.sqlframe_suite.compat import AnalysisException",
    ),
    (r"^(\s*)from sqlframe\.duckdb(?:\.session)? import ", r"\1from tests.sqlframe_suite.compat import "),
    # sqlframe.databricks needs databricks-sql-connector just to import.
    (
        r"^from sqlframe\.databricks import DatabricksSession$",
        "from tests.sqlframe_suite.compat import DatabricksSession",
    ),
]


def rewrite(text: str, source: str, ref: str, commit: str) -> str:
    for pattern, replacement in REWRITES:
        text = re.sub(pattern=pattern, repl=replacement, string=text, flags=re.MULTILINE)
    leftover = re.findall(pattern=r"^\s*(?:from|import) (?:pyspark|duckdb)\b.*$", string=text, flags=re.MULTILINE)
    allowed = (
        "from pyspark.sql import types",
        "from pyspark.sql import Window",
        "from pyspark.sql import SparkSession",
    )
    unexpected = [line.strip() for line in leftover if line.strip() not in allowed]
    if unexpected:
        raise SystemExit(f"{source}: imports the vendoring doesn't rewrite: {unexpected}")
    header = (
        f"# Vendored from eakmanrq/sqlframe {ref} ({commit[:7]}) {source} by\n"
        "# scripts/vendor_sqlframe_suite.py: mechanical rewrites only (see that script). Don't edit;\n"
        "# re-run the script. Upstream license: MIT.\n"
    )
    return header + text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--source", type=pathlib.Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        source = args.source
        if source is None:
            source = pathlib.Path(tmp) / "sqlframe"
            subprocess.run(
                args=["git", "clone", "--quiet", "--depth", "1", "--branch", args.ref, REPO, str(source)],
                check=True,
            )
        commit = subprocess.run(
            args=["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        if TARGET.exists():
            shutil.rmtree(path=TARGET)
        (TARGET / "tests" / "fixtures").mkdir(parents=True)
        (TARGET / "__init__.py").write_text(data="")
        engines = source / "tests" / "integration" / "engines"
        for name in SUITE_FILES:
            text = (engines / name).read_text()
            (TARGET / name).write_text(
                data=rewrite(text=text, source=f"tests/integration/engines/{name}", ref=args.ref, commit=commit)
            )
        duck = engines / "duck"
        for name, new_name in BACKEND_FILES.items():
            text = (duck / name).read_text()
            if name == "test_duckdb_catalog.py":
                if CATALOG_FIXTURE_OLD not in text:
                    raise SystemExit(f"{name}: its session fixture changed; update CATALOG_FIXTURE_OLD")
                text = text.replace(CATALOG_FIXTURE_OLD, CATALOG_FIXTURE_NEW)
            # The suite's fixtures for the one engine here are hardcharger_*.
            text = re.sub(pattern=r"\bduckdb_(session|employee)\b", repl=r"hardcharger_\1", string=text)
            (TARGET / new_name).write_text(
                data=rewrite(text=text, source=f"tests/integration/engines/duck/{name}", ref=args.ref, commit=commit)
            )
        for name in FIXTURE_FILES:
            shutil.copyfile(src=source / "tests" / "fixtures" / name, dst=TARGET / "tests" / "fixtures" / name)
        for name in FIXTURE_DIRS:
            shutil.copytree(src=source / "tests" / "fixtures" / name, dst=TARGET / "tests" / "fixtures" / name)
        shutil.copyfile(src=source / "LICENSE", dst=TARGET / "LICENSE")
        (TARGET / "UPSTREAM").write_text(data=f"{REPO} {args.ref} {commit}\n")
    print(
        f"vendored {len(SUITE_FILES) + len(BACKEND_FILES)} test files from {args.ref} ({commit[:7]}) into {TARGET.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
