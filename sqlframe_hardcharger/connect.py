from __future__ import annotations

import typing as t

from adbc_driver_hardcharger import dbapi as hardcharger_dbapi


class HardchargerAdbcCursor:
    """The DB-API cursor surface sqlframe uses, over a driver cursor.

    It proxies an explicit list of methods (no ``__getattr__`` passthrough),
    and makes closing idempotent and safe from ``__del__``.
    """

    def __init__(self, parent: "HardchargerConnection", inner: t.Any):
        self._parent = parent
        self._inner = inner
        self._closed = False

    # --- Context manager protocol -------------------------------------------------

    def __enter__(self) -> "HardchargerAdbcCursor":
        if self._closed:
            raise RuntimeError("Cursor already closed")
        return self

    def __exit__(self, exc_type: t.Any, exc: t.Any, tb: t.Any) -> t.Literal[False]:
        # Always close; never suppress the original exception.
        try:
            self.close()
        except Exception:
            pass
        return False

    # --- DB-API surface used by SQLFrame ------------------------------------------

    def _open_inner(self) -> t.Any:
        if self._closed:
            raise RuntimeError("Cursor is closed")
        return self._inner

    def execute(self, operation: t.Any, parameters: t.Any = None) -> t.Any:
        return self._open_inner().execute(operation=operation, parameters=parameters)

    def executemany(self, operation: t.Any, seq_of_parameters: t.Any) -> t.Any:
        return self._open_inner().executemany(operation=operation, seq_of_parameters=seq_of_parameters)

    def adbc_ingest(
        self,
        table_name: str,
        data: t.Any,
        mode: str = "create",
        *,
        catalog_name: t.Optional[str] = None,
        db_schema_name: t.Optional[str] = None,
        temporary: bool = False,
    ) -> int:
        return self._open_inner().adbc_ingest(
            table_name=table_name,
            data=data,
            mode=mode,
            catalog_name=catalog_name,
            db_schema_name=db_schema_name,
            temporary=temporary,
        )

    def set_statement_options(self, options: t.Dict[str, str]) -> None:
        """Set ADBC statement options (``adbc.warp.*``) on this cursor's statement."""
        self._open_inner().adbc_statement.set_options(**options)

    def fetchone(self) -> t.Any:
        return self._open_inner().fetchone()

    def fetchall(self) -> t.Any:
        return self._open_inner().fetchall()

    def fetchmany(self, size: t.Optional[int] = None) -> t.Any:
        inner = self._open_inner()
        if size is not None:
            return inner.fetchmany(size=size)
        return inner.fetchmany()

    def fetch_arrow_table(self) -> t.Any:
        return self._open_inner().fetch_arrow_table()

    @property
    def description(self) -> t.Any:
        return None if self._closed else self._inner.description

    @property
    def rowcount(self) -> int:
        return -1 if self._closed else self._inner.rowcount

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        inner = self._inner
        self._inner = None

        try:
            if inner is not None:
                try:
                    inner.close()
                except Exception:
                    # Don't leak teardown noise from a dead server.
                    pass
        finally:
            try:
                self._parent._unregister_cursor(cursor=self)
            except Exception:
                pass

    def __iter__(self) -> t.Iterator[t.Any]:
        if self._closed:
            return iter(())
        return iter(self._inner)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Never raise from GC
            pass


class HardchargerConnection:
    """A connection to a Hardcharger server, through ``adbc-driver-hardcharger``.

    Takes the keyword arguments of ``adbc_driver_hardcharger.dbapi.connect()``
    (``uri``, ``username``, ``password``, ``access_token``, ``auth_type``,
    ``tls_root_certs``, ``tls_client_cert``, ``tls_client_key``, ...), and:

    - tracks open cursors and closes them before the connection;
    - supports ``with`` for both connection and cursor;
    - exposes the ADBC attributes sqlframe's catalog reads.
    """

    def __init__(self, **connect_kwargs: t.Any):
        self._conn = hardcharger_dbapi.connect(**connect_kwargs)
        self._cursors: set[HardchargerAdbcCursor] = set()
        self._closed = False

    # --- Context manager protocol -------------------------------------------------

    def __enter__(self) -> "HardchargerConnection":
        if self._closed:
            raise RuntimeError("Connection already closed")
        return self

    def __exit__(self, exc_type: t.Any, exc: t.Any, tb: t.Any) -> t.Literal[False]:
        # DB-API semantics: roll back on an exception, else commit; always
        # close, without hiding the original exception.
        try:
            if exc_type is not None:
                try:
                    self.rollback()
                except Exception:
                    pass
            else:
                self.commit()
        finally:
            try:
                self.close()
            except Exception:
                pass
        return False

    # --- API used by SQLFrame -----------------------------------------------------

    def cursor(self) -> HardchargerAdbcCursor:
        if self._closed:
            raise RuntimeError("Connection already closed")

        cur = HardchargerAdbcCursor(parent=self, inner=self._conn.cursor())
        self._cursors.add(cur)
        return cur

    def execute(self, operation: t.Any, parameters: t.Any = None) -> HardchargerAdbcCursor:
        """Run one statement on a new cursor and return the cursor, as ``sqlite3`` and DuckDB
        connections do. The cursor closes with the connection (or call its ``close()``)."""
        cur = self.cursor()
        cur.execute(operation=operation, parameters=parameters)
        return cur

    def commit(self) -> None:
        if not self._closed:
            self._conn.commit()

    def rollback(self) -> None:
        if not self._closed:
            self._conn.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Close children first so ADBC is happy.
        for c in list(self._cursors):
            try:
                c.close()
            except Exception:
                pass
        self._cursors.clear()

        try:
            self._conn.close()
        except Exception:
            # Teardown against a dead server: nothing useful to raise.
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # --- Internal helper ----------------------------------------------------------

    def _unregister_cursor(self, cursor: HardchargerAdbcCursor) -> None:
        self._cursors.discard(cursor)

    # --- Pass-through properties --------------------------------------------------

    @property
    def adbc(self) -> hardcharger_dbapi.Connection:
        """The driver's DB-API connection, for low-level access (settings, tags, ...)."""
        return self._conn

    @property
    def adbc_current_catalog(self) -> t.Optional[str]:
        return getattr(self._conn, "adbc_current_catalog", None)

    @property
    def adbc_current_schema(self) -> t.Optional[str]:
        return getattr(self._conn, "adbc_current_db_schema", None)

    @property
    def database(self) -> t.Optional[str]:
        return self.adbc_current_catalog
