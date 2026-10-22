<p align="center">
  <a href="https://github.com/gizmodata/sqlframe-hardcharger">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/gizmodata/sqlframe-hardcharger/main/docs/assets/hardcharger-banner-dark.png">
      <img src="https://raw.githubusercontent.com/gizmodata/sqlframe-hardcharger/main/docs/assets/hardcharger-banner-light.png" alt="Hardcharger™" width="400">
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://pypi.org/project/sqlframe-hardcharger/"><img src="https://img.shields.io/pepy/dt/sqlframe-hardcharger.svg" alt="PyPI Downloads"></a>
  <a href="https://github.com/gizmodata/sqlframe-hardcharger/actions/workflows/ci.yml"><img src="https://github.com/gizmodata/sqlframe-hardcharger/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/sqlframe-hardcharger/"><img src="https://img.shields.io/badge/PyPI-sqlframe--hardcharger-blue.svg?logo=PyPI" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB.svg?logo=python&logoColor=white" alt="Python 3.11 to 3.14">
  <a href="https://github.com/eakmanrq/sqlframe"><img src="https://img.shields.io/badge/SQLFrame-4.5-31a8db.svg" alt="SQLFrame 4.5"></a>
  <a href="https://github.com/gizmodata/hardcharger-adbc"><img src="https://img.shields.io/badge/driver-adbc--driver--hardcharger-f15a24.svg" alt="adbc-driver-hardcharger"></a>
  <a href="https://github.com/gizmodata/warp-sql"><img src="https://img.shields.io/badge/protocol-Warp%20SQL-31a8db.svg" alt="Warp SQL protocol"></a>
  <a href="https://github.com/gizmodata/hardcharger"><img src="https://img.shields.io/badge/server-Hardcharger-f15a24.svg" alt="Hardcharger"></a>
  <a href="https://github.com/gizmodata/sqlframe-hardcharger/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-brightgreen.svg" alt="Apache 2.0 license"></a>
  <a href="https://gizmodata.com"><img src="https://img.shields.io/badge/by-GizmoData%E2%84%A2-f15a24.svg" alt="GizmoData™"></a>
</p>

<h3 align="center">Run your PySpark DataFrame code on Hardcharger™, with no Spark cluster.</h3>

---

## ⚡ What is it?

The [Hardcharger™](https://github.com/gizmodata/hardcharger) backend for
[SQLFrame](https://github.com/eakmanrq/sqlframe), which implements the PySpark DataFrame API on
SQL engines. Hardcharger is GizmoData™'s DuckDB 2.0 server; this package turns PySpark-style
transformations into DuckDB SQL and runs them there, so Spark and Databricks jobs move over by
swapping the session builder, not by rewriting them.

- **The PySpark API**: `SparkSession`, DataFrames, `functions`, `Window`, the catalog, and
  `activate()` so that unchanged `from pyspark.sql import ...` code runs on Hardcharger.
- **Bulk loading**: `session.ingest()` streams Arrow tables, record batch readers and pandas
  DataFrames in through ADBC bulk ingest, as one transaction.
- **Client-local files**: `spark.read.json()`/`.csv()`/`.parquet()` on files on *your* machine
  parse them client-side (Spark-style schema inference for JSON) and bulk-load them into
  temporary tables; the server needs no access to your file system.
- **Connections**: [`adbc-driver-hardcharger`](https://github.com/gizmodata/hardcharger-adbc),
  with `hardcharger://` URIs (TLS on by default, port 31337), password, access token, client
  certificate (mutual TLS) and browser (OAuth/SSO) sign-in, and OpenTelemetry traces of every
  statement.

## 📦 Install

```bash
pip install sqlframe-hardcharger
```

Python 3.11 or later. It installs SQLFrame, pyarrow and the driver,
`adbc-driver-hardcharger`, from PyPI. Both ship with Hardcharger 2.0.0.

## 🚀 Quick start

```python
from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.username", "hardcharger")
    .config("hardcharger.password", "change-me")
    .getOrCreate()
)

people = spark.createDataFrame(
    data=[(1, "Alice", 34), (2, "Bob", 27), (3, "Carol", 41)],
    schema=["id", "name", "age"],
)
people.filter(people.age > 30).select("name", "age").orderBy("age").show()
```

```text
+-------+-----+
|  name | age |
+-------+-----+
| Alice |  34 |
| Carol |  41 |
+-------+-----+
```

`hardcharger://host[:port]` is HTTPS on port 31337 unless the URI names another; the server's
certificate is verified. For a development server on plain HTTP, add `?tls=false`.

## 🐍 PySpark code, unchanged

`activate()` points the `pyspark` imports at Hardcharger, so existing PySpark code runs as is:

```python
from sqlframe_hardcharger import activate

activate(uri="hardcharger://localhost", username="hardcharger", password="change-me")

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark = SparkSession.builder.getOrCreate()

sales = spark.createDataFrame(
    data=[("east", "2026-10-01", 120.0), ("east", "2026-10-02", 80.0), ("west", "2026-10-01", 200.0)],
    schema=["region", "day", "amount"],
)
by_region = sales.groupBy("region").agg(F.sum("amount").alias("total"), F.count("*").alias("days"))
by_region.orderBy("region").show()

running = Window.partitionBy("region").orderBy("day")
sales.withColumn("running_total", F.sum("amount").over(running)).orderBy("region", "day").show()
```

`SparkSession` here *is* a `HardchargerSession`, so everything below (`spark.ingest()`,
the client-local readers) works through it too.

## 🔐 Connecting

Every setting is a `hardcharger.<name>` config key on the builder, or the same name as a keyword
argument of `activate()`. They are the keyword arguments of
`adbc_driver_hardcharger.dbapi.connect()`:

| Key | Meaning |
|---|---|
| `hardcharger.uri` | `hardcharger://host[:port]` (HTTPS, port 31337); `?tls=false` for plain HTTP |
| `hardcharger.username`, `hardcharger.password` | Password sign-in |
| `hardcharger.access_token` | An access token issued elsewhere, used as is |
| `hardcharger.auth_type` | `password` (default), `client_certificate` (mutual TLS, no password), or `external` (the server's browser sign-in, OAuth/SSO) |
| `hardcharger.tls_root_certs` | CA certificates to trust (PEM text or a file path) instead of the system's |
| `hardcharger.tls_skip_verify` | Don't verify the server's certificate (development only) |
| `hardcharger.tls_client_cert`, `hardcharger.tls_client_key` | Client certificate and key, for mutual TLS |
| `hardcharger.oauth_timeout`, `hardcharger.open_browser` | Browser sign-in: how long to wait, how to open the browser |
| `hardcharger.session_tag`, `hardcharger.query_tag` | JSON objects the server records with the session and its statements |
| `hardcharger.settings` | `hardcharger.*` session settings, e.g. `{"query_timeout": 60}` |
| `hardcharger.catalog`, `hardcharger.db_schema` | The session's current catalog and schema |
| `hardcharger.db_kwargs`, `hardcharger.conn_kwargs` | Any other ADBC option (`adbc.hardcharger.*`, `adbc.warp.*`, `adbc.telemetry.*`) |

A token from your identity platform:

```python
import os

from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.access_token", os.environ["HARDCHARGER_TOKEN"])
    .getOrCreate()
)
spark.sql("SELECT HARDCHARGER_USER() AS signed_in_as").show()
```

A client certificate, on a server started with `--mtls-ca-cert` and `--mtls-certificate-sign-in`
(the token the server issues is bound to the certificate):

```python
from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.auth_type", "client_certificate")
    .config("hardcharger.tls_client_cert", "client.pem")
    .config("hardcharger.tls_client_key", "client-key.pem")
    .getOrCreate()
)
spark.sql("SELECT HARDCHARGER_USER() AS signed_in_as").show()
```

Browser sign-in (`hardcharger.auth_type` = `external`) opens the server's sign-in page (a server
started with `--oauth-client-id`; the sign-in runs on the server's own port) and waits for you to
finish there.

A session is a process-wide singleton, as in SQLFrame: once one exists, `getOrCreate()` returns it
until you call `spark.stop()`.

## 📥 Bulk loading with `ingest()`

`createDataFrame()` sends rows as a SQL `VALUES` list, which is fine for a few thousand rows.
For anything bigger, `ingest()` streams Arrow data in through ADBC bulk ingest and returns a
DataFrame over the table:

```python
import pyarrow as pa

from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.username", "hardcharger")
    .config("hardcharger.password", "change-me")
    .getOrCreate()
)

events = pa.table(data={"event_id": list(range(1_000_000)), "kind": ["click", "view"] * 500_000})
df = spark.ingest(table_name="events", data=events, mode="replace")
df.groupBy("kind").count().orderBy("kind").show()
```

- `data`: a `pyarrow.Table`, `RecordBatch` or `RecordBatchReader`, or a `pandas.DataFrame`.
- `mode`: `create` (the default; fails if the table exists), `append`, `create_append` or
  `replace`.
- `temporary=True` makes a temporary table, visible to this session only.
- An ingest is one transaction: if it fails part-way, none of its rows remain.
- The driver sends an upload of several batches over up to 8 connections at once, so its rows
  land in no particular order; `ingest_parts=1` sends one ordered stream.

## 📂 Reading files on your machine

`spark.read.json()`, `.csv()`, `.parquet()` and `.load()` notice when the path (a file, a glob
or a directory) exists on the **client**, parse it there, and bulk-load it into a temporary
table. The server never needs to see your files:

```python
from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.username", "hardcharger")
    .config("hardcharger.password", "change-me")
    .getOrCreate()
)

with open("orders.jsonl", "w") as f:
    f.write('{"id": 1, "customer": {"name": "Alice", "tier": "gold"}, "items": [{"sku": "A1", "qty": 2}]}\n')
    f.write('{"id": 2, "customer": {"name": "Bob"}, "items": [], "note": "gift"}\n')

orders = spark.read.json("orders.jsonl")
orders.printSchema()
orders.select("id", orders["customer"]["name"].alias("customer")).orderBy("id").show()

with open("people.csv", "w") as f:
    f.write("id,name\n1,Alice\n2,Bob\n")
spark.read.csv("people.csv", header=True, inferSchema=True).show()
```

- **JSON schemas are inferred the way Spark does it**: one column per top-level key, objects as
  structs, arrays as arrays, fields sorted by name, and a field seen with conflicting types
  falling back to `string` (its JSON text). Inference streams the files, one record at a time,
  while they upload.
- One deliberate difference from Spark: a nested subtree with more than `maxNestedFields`
  fields (default 1000, counted recursively) stays one `JSON` column rather than an enormous
  struct; query it with `get_json_object()`. `.option("maxNestedFields", None)` expands
  everything.
- `.option("jsonDocument", True)` skips parsing: each document lands as text in a single `JSON`
  column, for data whose shape is too unstable to type.
- Also honored: `schema`, `header`, `sep`/`delimiter`, `multiLine`, `samplingRatio`,
  `filename`, `encoding`. Other options are ignored, with a warning; use
  `.option("serverSideRead", True)` to have the server read the path with DuckDB's own
  `read_json()`/`read_csv()`/`read_parquet()` (and all their options) instead.
- Rows keep the files' order (one ordered upload); `.option("ingestParts", 8)` uploads in
  parallel instead.
- A path the client can't see goes to the server as before (`read_csv(...)` on the server's
  file system), as do `s3://` and other remote URLs.

## 🔭 OpenTelemetry

The driver traces every statement (`Database.Open`, `Statement.ExecuteQuery`,
`Statement.ExecuteUpdate`) with OpenTelemetry. Turn it on with the standard `OTEL_*` environment
variables, or per session with the ADBC telemetry options:

```python
from sqlframe_hardcharger import HardchargerSession

spark = (
    HardchargerSession.builder.config("hardcharger.uri", "hardcharger://localhost")
    .config("hardcharger.username", "hardcharger")
    .config("hardcharger.password", "change-me")
    .config(
        "hardcharger.db_kwargs",
        {"adbc.telemetry.traces_exporter": "adbcfile", "adbc.telemetry.traces_folder_path": "traces"},
    )
    .getOrCreate()
)
spark.sql("SELECT 42 AS answer").show()
```

`adbcfile` writes the spans to files in `traces/`; `otlp` sends them to an OpenTelemetry
collector (`OTEL_EXPORTER_OTLP_ENDPOINT`).

## 🧭 Good to know

- Column names come back lowercased unless quoted (`formID` becomes `formid`), as in every
  SQLFrame backend; Spark keeps their case.
- Python UDFs (`spark.udf.register`) can't run: the server would have to call back into your
  Python process. Use `pyspark.sql.functions` or SQL.
- In `spark.sql()`, identifiers are quoted with backticks (the input dialect is Spark SQL,
  where double quotes are string literals).
- Hardcharger runs DuckDB 2.0. Lambdas (`F.transform`, `F.filter`, ...) are written in its
  `LAMBDA x : ...` syntax; the arrow form older DuckDB took is refused there.

### Coming from sqlframe-gizmosql

| sqlframe-gizmosql | sqlframe-hardcharger |
|---|---|
| `GizmoSQLSession`, `GizmoSQLDataFrame`, ... | `HardchargerSession`, `HardchargerDataFrame`, ... |
| `gizmosql.uri` = `grpc+tls://host:31337` or `gizmosql://host` | `hardcharger.uri` = `hardcharger://host` |
| `gizmosql.username`, `.password`, `.tls_skip_verify`, `.auth_type` | the same names under `hardcharger.`, plus `access_token`, `tls_root_certs`, client certificates and every other `connect()` argument |
| `gizmosql.max_msg_size` | gone: Warp SQL streams uploads over HTTP, with no message-size limit |
| `ingest()` appends staged through a temporary table | an ingest is one transaction; `ingest_parts` controls parallel upload |

## 🛠️ Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # plus adbc-driver-hardcharger from PyPI, or built from its repository
ruff check . && ruff format --check . && mypy
pytest tests/unit
SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY=/path/to/hardcharger-server pytest -n 4
```

The live tests (everything outside `tests/unit`) start their own `hardcharger-server`
processes on free 127.0.0.1 ports, from the binary in `SQLFRAME_HARDCHARGER_TEST_SERVER_BINARY`;
without it they fail rather than skip. CI takes that binary from the
`ghcr.io/gizmodata/hardcharger:main` image. They are this package's own tests
(`tests/integration`) and SQLFrame's engine suite (`tests/sqlframe_suite`, vendored from
SQLFrame's release by `scripts/vendor_sqlframe_suite.py` and run against Hardcharger as SQLFrame
runs it against DuckDB). Every Python block in this README runs against a live server in CI
(`scripts/run_readme_examples.py`).

## 📦 Releasing

[Semantic versioning](https://semver.org) and [CHANGELOG.md](https://github.com/gizmodata/sqlframe-hardcharger/blob/main/CHANGELOG.md). Pushing a `vX.Y.Z`
tag runs the full CI on the tagged commit, then builds the wheel and sdist and makes a GitHub
Release with the tag's CHANGELOG section.

## 📄 License

Apache License 2.0; see [LICENSE](https://github.com/gizmodata/sqlframe-hardcharger/blob/main/LICENSE). SQLFrame's engine tests in
`tests/sqlframe_suite/upstream` are MIT-licensed (see the LICENSE file there).

---

<p align="center">
  <a href="https://gizmodata.com"><img src="https://raw.githubusercontent.com/gizmodata/sqlframe-hardcharger/main/docs/assets/gizmodata-logo.png" alt="GizmoData™" width="56"></a><br>
  <sub>Built by <a href="https://gizmodata.com">GizmoData™</a></sub>
</p>

<p align="center"><sub>Hardcharger™ and GizmoData™ are trademarks of GizmoData LLC.</sub></p>
