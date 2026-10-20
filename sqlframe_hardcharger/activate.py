"""
activate() for sqlframe-hardcharger.

After ``activate(...)``, standard PySpark imports (``from pyspark.sql import
SparkSession``) resolve to this package, and their sessions run on a
Hardcharger server.
"""

from __future__ import annotations

import sys
import typing as t
from unittest.mock import MagicMock

if t.TYPE_CHECKING:
    from sqlframe_hardcharger.connect import HardchargerConnection

# The connection settings of the last activate() call: either "conn", or
# keyword arguments for adbc_driver_hardcharger.dbapi.connect().
ACTIVATE_CONFIG: t.Dict[str, t.Any] = {}


def activate(
    uri: t.Optional[str] = None,
    *,
    conn: t.Optional["HardchargerConnection"] = None,
    **connect_kwargs: t.Any,
) -> None:
    """
    Activate Hardcharger as the backend for PySpark imports.

    After calling this function, standard PySpark imports such as::

        from pyspark.sql import SparkSession
        from pyspark.sql import functions as F

    map to the Hardcharger equivalents.

    Parameters
    ----------
    uri : str, optional
        The server's URI: ``hardcharger://host[:port]`` (HTTPS, port 31337
        unless given; add ``?tls=false`` for a plain-HTTP development server).
    conn : HardchargerConnection, optional
        An existing connection to use. If given, ``uri`` and the connection
        keyword arguments are ignored.
    **connect_kwargs
        Any other keyword argument of ``adbc_driver_hardcharger.dbapi.connect()``:
        ``username``/``password``, ``access_token``,
        ``auth_type`` (``"password"``, ``"external"`` for the server's browser
        sign-in, or ``"client_certificate"``), ``tls_root_certs``,
        ``tls_skip_verify``, ``tls_client_cert``/``tls_client_key``,
        ``oauth_timeout``/``open_browser``,
        ``session_tag``/``query_tag``, ``settings``, ``catalog``/``db_schema``,
        ``db_kwargs``/``conn_kwargs``.

    Examples
    --------
    >>> from sqlframe_hardcharger import activate
    >>> activate(uri="hardcharger://localhost", username="hardcharger", password="change-me")
    >>> from pyspark.sql import SparkSession
    >>> spark = SparkSession.builder.getOrCreate()
    >>> spark.createDataFrame([(1, "hello")], ["id", "message"]).show()
    """
    import sqlframe_hardcharger
    from sqlframe_hardcharger import functions, types
    from sqlframe_hardcharger.session import CONNECT_OPTIONS

    unknown = sorted(set(connect_kwargs) - set(CONNECT_OPTIONS))
    if unknown:
        raise TypeError(f"activate() got unexpected keyword argument(s): {', '.join(unknown)}")

    ACTIVATE_CONFIG.clear()
    if conn is not None:
        ACTIVATE_CONFIG["conn"] = conn
    elif uri is not None or connect_kwargs.get("profile"):
        ACTIVATE_CONFIG.update({key: value for key, value in connect_kwargs.items() if value is not None})
        if uri is not None:
            ACTIVATE_CONFIG["uri"] = uri

    # Create pyspark mock module
    pyspark_mock = MagicMock()
    pyspark_mock.__file__ = "pyspark"
    pyspark_mock.__path__ = []
    sys.modules["pyspark"] = pyspark_mock

    # pyspark.sql is this package
    sys.modules["pyspark.sql"] = sqlframe_hardcharger
    pyspark_mock.sql = sqlframe_hardcharger

    # Hardcharger classes under their PySpark names
    setattr(sqlframe_hardcharger, "SparkSession", sqlframe_hardcharger.HardchargerSession)
    setattr(sqlframe_hardcharger, "DataFrame", sqlframe_hardcharger.HardchargerDataFrame)
    setattr(sqlframe_hardcharger, "DataFrameReader", sqlframe_hardcharger.HardchargerDataFrameReader)
    setattr(sqlframe_hardcharger, "DataFrameWriter", sqlframe_hardcharger.HardchargerDataFrameWriter)
    setattr(sqlframe_hardcharger, "GroupedData", sqlframe_hardcharger.HardchargerGroupedData)
    setattr(sqlframe_hardcharger, "Catalog", sqlframe_hardcharger.HardchargerCatalog)

    # Submodules
    sys.modules["pyspark.sql.session"] = sqlframe_hardcharger.session
    sys.modules["pyspark.sql.dataframe"] = sqlframe_hardcharger.dataframe
    sys.modules["pyspark.sql.column"] = sqlframe_hardcharger.column
    sys.modules["pyspark.sql.functions"] = functions
    sys.modules["pyspark.sql.types"] = types
    sys.modules["pyspark.sql.window"] = sqlframe_hardcharger.window
    sys.modules["pyspark.sql.catalog"] = sqlframe_hardcharger.catalog
    sys.modules["pyspark.sql.group"] = sqlframe_hardcharger.group
    sys.modules["pyspark.sql.readwriter"] = sqlframe_hardcharger.readwriter

    pyspark_mock.sql.functions = functions
    pyspark_mock.sql.types = types

    _patch_session_builder()


def _patch_session_builder() -> None:
    """Make every new session builder start from the activation config."""
    from sqlframe_hardcharger.session import HardchargerSession

    base_builder: t.Type[HardchargerSession.Builder] = HardchargerSession.Builder
    while getattr(base_builder, "_is_activate_builder", False):
        base_builder = base_builder.__bases__[0]

    class PatchedBuilder(base_builder):  # type: ignore[valid-type,misc]
        _is_activate_builder = True

        def __init__(self) -> None:
            super().__init__()
            if "conn" in ACTIVATE_CONFIG:
                self._session_kwargs["conn"] = ACTIVATE_CONFIG["conn"]
            else:
                self._hardcharger_connect_kwargs.update(
                    {key: value for key, value in ACTIVATE_CONFIG.items() if key != "conn"}
                )

    HardchargerSession.builder = PatchedBuilder()
    HardchargerSession.Builder = PatchedBuilder  # type: ignore[misc]
