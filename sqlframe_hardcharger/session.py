from __future__ import annotations

import contextlib
import datetime
import logging
import time
import typing as t
from functools import cached_property

import pyarrow as pa
import sqlglot
from sqlframe.base.session import _BaseSession
from sqlframe.base.util import normalize_string
from sqlglot.dialects.dialect import Dialect
from sqlglot.helper import ensure_list

from sqlframe_hardcharger.catalog import HardchargerCatalog
from sqlframe_hardcharger.dataframe import HardchargerDataFrame
from sqlframe_hardcharger.dialect import for_hardcharger
from sqlframe_hardcharger.readwriter import (
    HardchargerDataFrameReader,
    HardchargerDataFrameWriter,
)
from sqlframe_hardcharger.table import HardchargerTable
from sqlframe_hardcharger.udf import HardchargerUDFRegistration

if t.TYPE_CHECKING:
    import pandas as pd

    from sqlframe_hardcharger.connect import HardchargerAdbcCursor, HardchargerConnection

else:
    HardchargerConnection = t.Any
    HardchargerAdbcCursor = t.Any

logger = logging.getLogger(__name__)

IngestMode = t.Literal["append", "create", "replace", "create_append"]

# A pyarrow.Table is re-batched to about this many bytes per record batch
# before it is streamed. Warp SQL has no message-size limit (an ingest is one
# streamed HTTP request, or several in parallel, committed as one
# transaction), so this is not about fitting a limit: one giant batch would go
# over a single connection, while many moderate batches let the driver spread
# a partitioned ingest over several connections and keep memory per batch
# bounded on both ends.
_INGEST_TARGET_BATCH_BYTES = 8 * 1024 * 1024

#: The statement option that caps how many connections one bulk ingest uses
#: (``adbc.warp.ingest.parts``; the driver's default is 8). 1 sends one ordered
#: stream, so rows land in the table in the order they were sent.
INGEST_PARTS_OPTION = "adbc.warp.ingest.parts"

# The keyword arguments of adbc_driver_hardcharger.dbapi.connect() that the
# session builder takes as ``hardcharger.<name>`` config keys, and activate()
# as keyword arguments.
CONNECT_OPTIONS: t.Tuple[str, ...] = (
    "uri",
    "profile",
    "username",
    "password",
    "access_token",
    "auth_type",
    "oauth_url",
    "oauth_port",
    "oauth_timeout",
    "open_browser",
    "session_tag",
    "query_tag",
    "settings",
    "tls_skip_verify",
    "tls_root_certs",
    "tls_client_cert",
    "tls_client_key",
    "catalog",
    "db_schema",
    "db_kwargs",
    "conn_kwargs",
)

CONFIG_PREFIX = "hardcharger."


def _catalog_column_key(name: str) -> str:
    """A column name as sqlframe's catalog / session.sql() (Spark input dialect) expects it:
    backtick-quoted, so names with spaces, dots or reserved words survive."""
    return "`" + name.replace("`", "``") + "`"


def _rebatched_reader(table: pa.Table) -> pa.RecordBatchReader:
    bytes_per_row = table.nbytes / max(table.num_rows, 1)
    rows_per_batch = max(1, min(table.num_rows, int(_INGEST_TARGET_BATCH_BYTES / max(bytes_per_row, 1))))
    batches = table.to_batches(max_chunksize=rows_per_batch)
    return pa.RecordBatchReader.from_batches(schema=table.schema, batches=iter(batches))


class HardchargerSession(
    _BaseSession[
        HardchargerCatalog,
        HardchargerDataFrameReader,
        HardchargerDataFrameWriter,
        HardchargerDataFrame,
        HardchargerTable,
        HardchargerConnection,  # type: ignore[type-var]
        HardchargerUDFRegistration,
    ]
):
    _catalog = HardchargerCatalog
    _reader = HardchargerDataFrameReader
    _writer = HardchargerDataFrameWriter
    _df = HardchargerDataFrame
    _table = HardchargerTable
    _udf_registration = HardchargerUDFRegistration

    def __init__(self, conn: t.Optional[HardchargerConnection] = None):
        if not hasattr(self, "_conn"):
            super().__init__(conn=conn)
            self._last_result = None

    @property
    def execution_dialect(self) -> Dialect:
        return self._execution_dialect

    @execution_dialect.setter
    def execution_dialect(self, dialect: Dialect) -> None:
        # Both __init__ and the builder's getOrCreate() assign a fresh `duckdb` dialect here;
        # whichever does, it writes SQL for Hardcharger's DuckDB 2.0 (see dialect.py).
        self._execution_dialect = for_hardcharger(dialect=dialect)

    @cached_property
    def _cur(self) -> HardchargerAdbcCursor:  # type: ignore[override]
        return self._conn.cursor()

    @classmethod
    def _try_get_map(cls, value: t.Any) -> t.Optional[t.Dict[str, t.Any]]:
        if value and isinstance(value, dict):
            # A dict with a non-string key can't be a struct's fields, so it is a map.
            if len([k for k in value if not isinstance(k, str)]) > 0:
                return value
        return None

    @classmethod
    def _to_value(cls, value: t.Any) -> t.Any:
        # Rows come from Arrow (pyarrow's to_pylist), not from DuckDB's own Python client,
        # which sqlframe's DuckDB backend reads. Make them what that client gives:
        # - a MAP is a list of (key, value) tuples (no other Arrow type becomes a tuple:
        #   structs are dicts, lists are lists); DuckDB gives a dict;
        # - an INTERVAL is a pyarrow.MonthDayNano (a tuple too); DuckDB gives a timedelta,
        #   counting a month as 30 days.
        if isinstance(value, pa.MonthDayNano):
            return datetime.timedelta(days=value.months * 30 + value.days, microseconds=value.nanoseconds / 1000)
        if value and isinstance(value, list) and all(isinstance(item, tuple) and len(item) == 2 for item in value):
            value = dict(value)
        return super()._to_value(value)

    def _execute(self, sql: str) -> None:
        self._last_result = self._cur.execute(sql)

    def _collect(
        self,
        expressions: t.Union[str, sqlglot.exp.Expr, t.List[str], t.List[sqlglot.exp.Expr]],
        *,
        quote_identifiers: bool = True,
        skip_normalization: bool = False,
        skip_rows: bool = False,
    ) -> t.List[t.Any]:
        rows = super()._collect(
            expressions,
            quote_identifiers=quote_identifiers,
            skip_normalization=skip_normalization,
            skip_rows=skip_rows,
        )
        if rows or skip_rows:
            return rows
        # DuckDB answers INSERT/UPDATE/DELETE/MERGE with one row holding the affected row
        # count, and sqlframe's table API (df.update(...).execute()) returns that; Warp SQL
        # reports it as the statement's row count instead of a result set.
        last = ensure_list(expressions)[-1]
        if isinstance(last, (sqlglot.exp.Insert, sqlglot.exp.Update, sqlglot.exp.Delete, sqlglot.exp.Merge)):
            if self._cur.description is None and self._cur.rowcount >= 0:
                return [self._to_row(columns=["count"], values=[self._cur.rowcount])]
        return rows

    def sql(self, sqlQuery, dialect=None, qualify: bool = True):
        """Like the base ``sql()``, but self-healing for tables sqlframe
        doesn't know yet.

        sqlframe qualifies queries against its in-session schema registry and
        rejects references to unregistered tables ("Column 'x' could not be
        resolved") — but tables created via ``spark.sql("CREATE TABLE ...")``
        or existing on the server are never auto-registered. On that failure,
        introspect each referenced table through the catalog (DESCRIBE) and
        retry once, so plain PySpark flows like CTAS-then-SELECT just work.
        """
        try:
            return super().sql(sqlQuery, dialect=dialect, qualify=qualify)
        except sqlglot.errors.OptimizeError:
            expression = (
                sqlglot.parse_one(sql=sqlQuery, read=dialect or self.input_dialect)
                if isinstance(sqlQuery, str)
                else sqlQuery
            )
            registered_any = False
            for table in expression.find_all(sqlglot.exp.Table):
                with contextlib.suppress(Exception):
                    # No-op for already-known tables; CTE aliases and truly
                    # missing tables fail introspection and are skipped.
                    self._register_table_for_qualify(table=table)
                    registered_any = True
            if not registered_any:
                raise
            # sqlglot's MappingSchema caches find() results keyed by the
            # exp.Table node; the failed qualify above cached an empty result
            # under a node shape (aliased) that add_table's invalidation
            # doesn't match, so the stale miss would survive the retry.
            find_cache = getattr(self.catalog._schema, "_find_cache", None)
            if find_cache is not None:
                find_cache.clear()
            return super().sql(sqlQuery, dialect=dialect, qualify=qualify)

    def _register_table_for_qualify(self, table: sqlglot.exp.Table) -> None:
        """Register one referenced table's columns with sqlframe's catalog.

        Introspects under the reference's full qualification (db/catalog,
        minus any alias), so e.g. ``information_schema.tables`` or a table in
        another schema is described correctly, then registers the columns
        with :meth:`_add_table_matching_depth`.
        """
        qualified = sqlglot.exp.table_(table=table.this, db=table.args.get("db"), catalog=table.args.get("catalog"))
        if self.catalog._schema.find(table=qualified, raise_on_missing=False):
            return
        column_mapping = {
            normalize_string(value=name, from_dialect="output", to_dialect="input", is_column=True): normalize_string(
                value=data_type.sql(dialect=self.output_dialect),
                from_dialect="output",
                to_dialect="input",
                is_datatype=True,
            )
            for name, data_type in self.catalog.get_columns(table=qualified).items()
        }
        self._add_table_matching_depth(table_name=table.name, column_mapping=column_mapping)

    def _add_table_matching_depth(self, table_name: str, column_mapping: t.Dict[str, str]) -> None:
        """Register ``table_name``'s columns with sqlframe's catalog, at the
        catalog's nesting depth.

        sqlglot's MappingSchema fixes its depth from the first table
        registered (1: bare names; 2: ``db.table``; 3: ``catalog.db.table``)
        and refuses any other depth afterwards. Its lookup matches a table
        reference's trailing name parts, so a bare reference still finds a
        table registered under the current database (and catalog). An empty
        catalog gets the bare name, which keeps it at depth 1: registering a
        qualified name first (``information_schema.tables``, say) used to fix
        it at depth 2 and break every later client-local read, which
        registers bare names.
        """
        schema = self.catalog._schema
        depth = 1 if schema.empty else schema.depth()
        table = sqlglot.exp.table_(
            table=sqlglot.exp.to_identifier(name=table_name),
            db=sqlglot.exp.to_identifier(name=self.catalog.currentDatabase()) if depth >= 2 else None,
            catalog=sqlglot.exp.to_identifier(name=self.catalog.currentCatalog()) if depth >= 3 else None,
        )
        if schema.find(table=table, raise_on_missing=False):
            # sqlframe's add_table() keeps a known table's first schema; this one changed
            # (ingest(mode="replace") with other columns, say), so replace it.
            schema.add_table(table, column_mapping, dialect=self.input_dialect)
            find_cache = getattr(schema, "_find_cache", None)
            if find_cache is not None:
                find_cache.clear()
            return
        self.catalog.add_table(table=table, column_mapping=column_mapping)

    def _dataframe_over_table(self, table_name: str) -> HardchargerDataFrame:
        """A DataFrame over ``table_name`` (a bare name; temporary tables too) with its columns
        spelled out and registered with sqlframe's catalog, so the DataFrame has a concrete
        schema: a lazy ``SELECT *`` breaks e.g. ``createOrReplaceTempView()``, and once any
        table schema is known, sqlglot's qualify rejects columns of unregistered tables.

        The catalog's own listColumns() can't see TEMPORARY tables, so this introspects with
        DESCRIBE. A column type sqlglot can't parse (an all-NULL list column is ``"NULL"[]``)
        leaves a plain ``SELECT *``, as before.
        """
        self._cur.execute(f"DESCRIBE {table_name}")
        described = self._cur.fetchall()
        try:
            column_mapping = {
                _catalog_column_key(name=column_name): sqlglot.exp.DataType.build(dtype=type_str, dialect="duckdb").sql(
                    dialect=self.input_dialect
                )
                for column_name, type_str, *_ in described
            }
        except sqlglot.errors.ParseError:
            logger.info("Column types of %s don't parse; reading it with SELECT *", table_name)
            return self.sql(f"SELECT * FROM {table_name}")
        self._add_table_matching_depth(table_name=table_name, column_mapping=column_mapping)
        select_list = ", ".join(_catalog_column_key(name=column_name) for column_name, *_ in described)
        return self.sql(f"SELECT {select_list} FROM {table_name}")

    @property
    def _is_duckdb(self) -> bool:
        return True

    def ingest(
        self,
        table_name: str,
        data: t.Union["pa.Table", "pa.RecordBatch", "pa.RecordBatchReader", "pd.DataFrame"],
        mode: IngestMode = "create",
        temporary: bool = False,
        ingest_parts: t.Optional[int] = None,
    ) -> HardchargerDataFrame:
        """Bulk-load Arrow or pandas data into a Hardcharger table with ADBC ``adbc_ingest()``.

        The data streams to the server as columnar Arrow record batches over
        the session's connection (Warp SQL bulk ingest), instead of the
        row-by-row SQL ``VALUES`` path :meth:`createDataFrame` uses, which is
        much faster for anything beyond a few thousand rows. An ingest is one
        transaction: if it fails, none of its rows remain.

        Parameters
        ----------
        table_name : str
            The table to create, append to, or replace.
        data : pyarrow.Table | pyarrow.RecordBatch | pyarrow.RecordBatchReader | pandas.DataFrame
            The data. A ``Table`` (or ``RecordBatch``, or ``pandas.DataFrame``)
            is re-batched into batches of a few MB, so a large table is
            streamed rather than sent as one buffer; a ``RecordBatchReader``
            is sent as it comes.
        mode : str, default "create"
            ``"create"`` (error if the table exists), ``"append"`` (error if
            it does not), ``"create_append"`` (create if missing, then
            append), or ``"replace"`` (drop it if it exists, then create).
        temporary : bool, default False
            Create ``table_name`` as a temporary table, scoped to this
            session: other sessions can't see it, and it goes away when the
            session ends. ``spark.read.json()``/``.csv()``/``.parquet()`` use
            this for client-local files.
        ingest_parts : int, optional
            The most connections the upload is spread over at once (the
            driver's default is 8). ``1`` sends one ordered stream, so the
            rows land in the order they were sent; with more, an upload of
            several batches lands in no defined order.

        Returns
        -------
        HardchargerDataFrame
            A DataFrame over the now-populated ``table_name``.
        """
        with contextlib.suppress(ImportError):
            from pandas import DataFrame as pd_DataFrame

            if isinstance(data, pd_DataFrame):
                data = pa.Table.from_pandas(df=data)

        if isinstance(data, pa.RecordBatch):
            data = pa.Table.from_batches(batches=[data])

        started = time.perf_counter()
        # A dedicated, short-lived cursor, so the ingest statement's options
        # (target table, mode, parts) never stick to the session's shared
        # cursor. It shares the connection, and so the session: temporary
        # tables it creates are visible to the session's other cursors.
        with self._conn.cursor() as ingest_cur:
            if ingest_parts is not None:
                ingest_cur.set_statement_options(options={INGEST_PARTS_OPTION: str(int(ingest_parts))})
            if isinstance(data, pa.Table):
                rows = data.num_rows
                payload: t.Any = _rebatched_reader(table=data)
            else:
                rows = None
                payload = data
            ingested = ingest_cur.adbc_ingest(table_name=table_name, data=payload, mode=mode, temporary=temporary)
        logger.info(
            "Ingested %s rows into %s in %.2fs",
            ingested if ingested is not None and ingested >= 0 else rows,
            table_name,
            time.perf_counter() - started,
        )
        if "." in table_name or '"' in table_name or "`" in table_name:
            # A qualified or quoted name: not one _dataframe_over_table() registers.
            return self.sql(f"SELECT * FROM {table_name}")
        return self._dataframe_over_table(table_name=table_name)

    class Builder(_BaseSession.Builder):
        DEFAULT_EXECUTION_DIALECT = "duckdb"

        # Hardcharger connection settings: "hardcharger.<name>", where <name>
        # is a keyword argument of adbc_driver_hardcharger.dbapi.connect().
        HARDCHARGER_URI_KEY = "hardcharger.uri"
        HARDCHARGER_USERNAME_KEY = "hardcharger.username"
        HARDCHARGER_PASSWORD_KEY = "hardcharger.password"
        HARDCHARGER_ACCESS_TOKEN_KEY = "hardcharger.access_token"
        HARDCHARGER_AUTH_TYPE_KEY = "hardcharger.auth_type"
        HARDCHARGER_TLS_SKIP_VERIFY_KEY = "hardcharger.tls_skip_verify"
        HARDCHARGER_TLS_ROOT_CERTS_KEY = "hardcharger.tls_root_certs"
        HARDCHARGER_TLS_CLIENT_CERT_KEY = "hardcharger.tls_client_cert"
        HARDCHARGER_TLS_CLIENT_KEY_KEY = "hardcharger.tls_client_key"

        def __init__(self) -> None:
            super().__init__()
            self._hardcharger_connect_kwargs: t.Dict[str, t.Any] = {}

        def _set_config(
            self,
            key: t.Optional[str] = None,
            value: t.Optional[t.Any] = None,
            *,
            map: t.Optional[t.Dict[str, t.Any]] = None,
        ) -> None:
            if map:
                remaining = {}
                for map_key, map_value in map.items():
                    if not self._set_hardcharger_option(key=map_key, value=map_value):
                        remaining[map_key] = map_value
                map = remaining
            if key is not None and self._set_hardcharger_option(key=key, value=value):
                key = None
                value = None
            super()._set_config(key=key, value=value, map=map)

        def _set_hardcharger_option(self, key: str, value: t.Any) -> bool:
            """Take a ``hardcharger.<name>`` key; False if it isn't one."""
            if not key.startswith(CONFIG_PREFIX):
                return False
            name = key[len(CONFIG_PREFIX) :]
            if name not in CONNECT_OPTIONS:
                raise ValueError(
                    f"unknown Hardcharger config key {key!r}: expected one of "
                    + ", ".join(CONFIG_PREFIX + option for option in CONNECT_OPTIONS)
                )
            if value is None:
                self._hardcharger_connect_kwargs.pop(name, None)
            elif name == "tls_skip_verify":
                self._hardcharger_connect_kwargs[name] = str(value).lower() in ("true", "1")
            elif name == "oauth_port":
                self._hardcharger_connect_kwargs[name] = int(value)
            elif name == "oauth_timeout":
                self._hardcharger_connect_kwargs[name] = float(value)
            else:
                self._hardcharger_connect_kwargs[name] = value
            return True

        @cached_property
        def session(self) -> HardchargerSession:
            kwargs = self._hardcharger_connect_kwargs
            if (kwargs.get("uri") or kwargs.get("profile")) and "conn" not in self._session_kwargs:
                from sqlframe_hardcharger.connect import HardchargerConnection

                self._session_kwargs["conn"] = HardchargerConnection(**kwargs)

            return HardchargerSession(**self._session_kwargs)

        def getOrCreate(self) -> HardchargerSession:
            return super().getOrCreate()  # type: ignore[return-value]

    builder = Builder()
