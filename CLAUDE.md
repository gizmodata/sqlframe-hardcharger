# CLAUDE.md: sqlframe-hardcharger

The Hardcharger™ backend for [SQLFrame](https://github.com/eakmanrq/sqlframe) (PySpark DataFrame
API on SQL engines), ported from gizmodata/sqlframe-gizmosql. Hardcharger is not announced:
this repository is internal, nothing is published to PyPI, and no tag is pushed without
Philip's go-ahead. Never push Hardcharger work to the public sqlframe-gizmosql repository.

## Architecture

- **Driver**: `adbc-driver-hardcharger` (gizmodata/hardcharger-adbc, internal, not on PyPI):
  `hardcharger://` URIs (HTTPS, port 31337), Warp SQL over HTTP. `connect.py` wraps its DB-API
  connection: `HardchargerConnection(**connect_kwargs)` takes `dbapi.connect()`'s keyword
  arguments; `HardchargerAdbcCursor` proxies an explicit list of cursor methods (add a method
  there to reach it through the session).
- **Session** (`session.py`): `HardchargerSession`, a process-wide singleton
  (`_BaseSession._instance`) as in every SQLFrame backend: `getOrCreate()` returns the first
  session until `.stop()`. The builder takes `hardcharger.<name>` keys, `<name>` in
  `CONNECT_OPTIONS` (the driver's `connect()` arguments); unknown `hardcharger.*` keys raise.
- **Execution dialect** (`dialect.py`): the `duckdb` sqlglot dialect, with this session's
  instance given a generator that writes DuckDB 2.0's `LAMBDA x : ...` (2.0 refuses `x -> ...`).
  It must stay the DuckDB dialect *type*: sqlframe looks engines and functions up by it.
- **Rows** come from Arrow (`to_pylist`), not DuckDB's Python client: `_to_value` turns MAPs
  (lists of 2-tuples) into dicts and `MonthDayNano` intervals into timedeltas, matching what
  sqlframe's DuckDB backend sees.
- **activate()** (`activate.py`) maps `pyspark.sql` to this package; `SparkSession` *is*
  `HardchargerSession`. Builders created after `activate()` start from its config.

## Bulk ingest and client-local reads

- `ingest()` re-batches a Table to ~8 MiB batches and calls `adbc_ingest()` on a dedicated
  cursor. An ingest is one transaction (Warp SQL), so there is no staging or size-limit retry
  (sqlframe-gizmosql needed both for gRPC's 16 MiB messages). The driver uploads 2+ batches over
  up to 8 connections (`adbc.warp.ingest.parts`), so rows land unordered unless
  `ingest_parts=1`. Client-local reads pass 1 by default (Spark keeps file order).
- `_dataframe_over_table()` DESCRIBEs the table, registers its columns and selects them by name;
  a lazy `SELECT *` breaks `createOrReplaceTempView()`. `_add_table_matching_depth()` registers
  at the catalog's nesting depth (sqlglot fixes it from the first registration and refuses other
  depths) and replaces a stale schema.
- JSON: `json_schema.py` infers Spark-style while the raw documents stream into a `_raw` temp
  table; `CREATE TEMP TABLE ... AS SELECT from_json("json", '<structure>').*` expands them. Keep
  `from_json` (lenient); `CAST(json AS STRUCT(...))` errors on a missing key. JSON reads must
  stream, never accumulate documents.
- In `session.sql()` strings, quote identifiers with backticks (the input dialect is Spark).

## Tests

- `tests/unit`: no server. Don't construct a real `HardchargerSession` there (singleton leaks).
- Everything else is live: `tests/hardcharger_server.py` starts `hardcharger-server` from
  `SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY` on free 127.0.0.1 ports (TLS with a throwaway CA,
  optional client certificates, certificate sign-in), with a clean environment. Without the
  binary the tests FAIL; never make them skip. Test variables are `SQLFRAME_HARDCHARGER_TEST_*`.
- `tests/sqlframe_suite/upstream` is SQLFrame's engine suite, vendored by
  `scripts/vendor_sqlframe_suite.py` (mechanical rewrites only; don't edit, re-run the script).
  `compat.py` binds its DuckDB names to the Hardcharger classes. `KNOWN_FAILURES` in that
  conftest are strict xfails with the exception they must raise; each needs a reason outside
  this package.
- On macOS, run the live tests in a Linux container from the server image (the binary is
  Linux-only), with the driver library built for Linux.
- `scripts/run_readme_examples.py` runs every ```python block of the README against a server on
  port 31337 (user `hardcharger`, password `change-me`, CA trusted via `SSL_CERT_FILE`).

## Releases

Version in `pyproject.toml` only; CHANGELOG in Keep-a-Changelog form. `release.yml` runs on `v*`
tags: the full CI (`workflow_call`, `secrets: inherit`), then build and a GitHub Release. No
PyPI publish job until Philip says so.

## Code style

Keyword arguments at call sites wherever the callee accepts them, including third-party calls.
