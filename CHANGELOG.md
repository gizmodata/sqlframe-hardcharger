# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- sqlframe-hardcharger now uses the Chargewire protocol and drivers, the new name of the protocol
  `adbc-driver-hardcharger` speaks; statement options are `adbc.chargewire.*`. It still works with
  Hardcharger servers released before the rename, and with drivers that only know the earlier
  option names.

## [2.0.1] - 2026-10-22

### Documentation

- Add a total PyPI downloads badge to the README and PyPI description.
- Fix the banner and footer logos on PyPI with absolute image URLs, and make repository file links absolute.

## [2.0.0] - 2026-10-21

### Changed
- Require the released Hardcharger ADBC 2.0.0 driver and test the final driver implementation.

The first release. Its version follows the Hardcharger server's (2.0.0); 0.1.0 below was built but
never published.

### Changed

- `release.yml` publishes to PyPI through trusted publishing (the `pypi` environment, after an
  approval on the `release` environment) before creating the GitHub Release. The build refuses
  to go on while the `adbc-driver-hardcharger` floor in `pyproject.toml` is not on PyPI, and
  checks that the wheel depends on the driver by that plain floor, never by CI's git pin.
- The repository's public files: NOTICE (naming sqlframe-gizmosql as the origin),
  CONTRIBUTING.md with the Developer Certificate of Origin sign-off, SECURITY.md,
  CODE_OF_CONDUCT.md, and the LICENSE copyright line.

- Browser sign-in (`hardcharger.auth_type` = `external`) runs on the server's own port (Chargewire
  protocol 1.0.0, spec §4.3): the `hardcharger.oauth_url` and `hardcharger.oauth_port` options are
  gone, with `adbc-driver-hardcharger`'s. `oauth_timeout` and `open_browser` stay.
- The driver is built from hardcharger-adbc `13f4eb4` (Chargewire 1.0.0, on chargewire-adbc `a81c326`;
  was `9a087be`), tested against `hardcharger-server` 2.0.0-rc.1. SQL errors from it are
  `ProgrammingError`, not `InternalError`; a plain-HTTP server reached with TLS says so.
- The live tests start browser sign-in servers with `--oauth-base-url`; the mock identity
  provider has an authorization endpoint (PKCE S256, nonce, one-time codes) and the stand-in
  browser follows its redirect, as a browser does.
- `test_array_distinct` from SQLFrame's suite is marked platform-dependent: DuckDB 2.0's
  `list_distinct` returns elements in hash order, which differs between macOS and Linux.

### Documentation

- The README banner is the new Hardcharger™ logo, the bull mascot lockup in a light and a dark
  version that follows the reader's color scheme, in place of the GizmoData banner card.

## [0.1.0] - 2026-10-19

The Hardcharger™ port of sqlframe-gizmosql 1.6.1: the same PySpark DataFrame API on
Hardcharger, GizmoData™'s DuckDB 2.0 server, through `adbc-driver-hardcharger` and the Chargewire
SQL protocol.

### Added

- `HardchargerSession`, `HardchargerDataFrame` and the rest of the SQLFrame backend, and
  `activate()` for unchanged `from pyspark.sql import ...` code.
- Connections through `adbc-driver-hardcharger`: `hardcharger://` URIs (TLS on by default, port
  31337), and every `connect()` argument as a `hardcharger.<name>` builder key or `activate()`
  keyword: password, access token, client certificate (`auth_type="client_certificate"`, mutual
  TLS) and browser (`auth_type="external"`, OAuth/SSO) sign-in, `tls_root_certs`, session and
  query tags, session settings, and raw ADBC options (`db_kwargs`, `conn_kwargs`).
- `session.ingest()` (ADBC bulk ingest of Arrow tables, record batch readers and pandas
  DataFrames), now one transaction per ingest, with `ingest_parts` to choose between the
  driver's parallel upload and one ordered stream.
- Client-local `spark.read.json()`/`.csv()`/`.parquet()` with Spark-style JSON schema
  inference, the `maxNestedFields` budget and `jsonDocument` mode. Reads keep the files' row
  order by default (`.option("ingestParts", n)` uploads in parallel).
- OpenTelemetry spans for every statement, from the driver (`adbc.telemetry.*` options, or the
  `OTEL_*` environment variables).
- Tests against a live `hardcharger-server` from `ghcr.io/gizmodata/hardcharger:main`: this
  package's own suite (TLS, every sign-in method, ingest, reads, telemetry) and SQLFrame 4.5.0's
  engine suite plus its DuckDB backend tests, vendored by `scripts/vendor_sqlframe_suite.py`.
  Live tests fail, never skip, without a server.
- CI: ruff and mypy gates, unit tests on Python 3.11 to 3.14, live tests on 3.11 and 3.14 and
  with the lowest allowed dependency versions, every README example run against a live server,
  and a release workflow gated on all of it.

### Changed (from sqlframe-gizmosql)

- DuckDB 2.0 refuses single-arrow lambdas (`x -> x + 1`); sessions write `LAMBDA x : x + 1`,
  so `transform`, `filter`, `array_compact` and the other lambda functions work.
- Rows read through Arrow are made what DuckDB's Python client gives: MAP values become dicts
  (struct-like ones become Rows) and INTERVALs become `timedelta`s.
- `table.update(...)`/`.delete(...)`/`.merge(...)` `.execute()` return the affected row
  count, as on DuckDB.
- DataFrames from `ingest()` and client-local CSV/Parquet reads have their columns spelled out
  and registered, so `createOrReplaceTempView()` works on them; a re-ingested table with new
  columns gets its new schema.
- A session whose first query names a qualified table (`information_schema.tables`) no longer
  breaks later client-local reads ("must match the schema's nesting level"), so sqlglot 30.22
  needs no cap.
- An empty JSON input reads as an empty DataFrame instead of failing schema inference.
- `spark.catalog.listCatalogs()`/`listDatabases()`/`listTables()` leave out the server's own
  `_hardcharger_system` catalog.
- `spark.udf.register()` says Python UDFs can't run on a server, instead of an `AttributeError`.

### Removed (from sqlframe-gizmosql)

- `gizmosql.max_msg_size` and the size-limit retries around ingest and JSON reads: Chargewire
  streams uploads over HTTP with no message-size limit.
- The staging table behind `ingest(mode="append")`: an ingest is one transaction.
- The workaround for fetching after DDL/DML, which `adbc-driver-hardcharger` handles.

[Unreleased]: https://github.com/gizmodata/sqlframe-hardcharger/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/gizmodata/sqlframe-hardcharger/releases/tag/v0.1.0
