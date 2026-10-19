"""Names the vendored SQLFrame suite imports, bound for Hardcharger (see
scripts/vendor_sqlframe_suite.py).

Hardcharger runs DuckDB, so the suite's DuckDB backend names are the Hardcharger classes, and
every "if DuckDB" branch of the suite (expected values, documented DuckDB gaps) applies to it.
The PySpark and Databricks names are stand-ins: the suite only checks sessions against them with
``isinstance``, and no such session exists here.
"""

from __future__ import annotations

from sqlframe_hardcharger import (
    HardchargerCatalog as DuckDBCatalog,
)
from sqlframe_hardcharger import (
    HardchargerDataFrame as DuckDBDataFrame,
)
from sqlframe_hardcharger import (
    HardchargerSession as DuckDBSession,
)
from sqlframe_hardcharger import functions

__all__ = [
    "AnalysisException",
    "DatabricksSession",
    "DuckDBCatalog",
    "DuckDBDataFrame",
    "DuckDBSession",
    "PySparkSession",
    "functions",
]


class PySparkSession:
    """Stand-in for pyspark.sql.SparkSession: never instantiated."""


class DatabricksSession:
    """Stand-in for sqlframe.databricks.DatabricksSession: never instantiated."""


class AnalysisException(Exception):
    """Stand-in for pyspark's AnalysisException: never raised."""
