"""How a Hardcharger session writes DuckDB SQL.

Sessions keep sqlglot's ``duckdb`` dialect (sqlframe looks engines up by dialect type, so a
dialect of our own would break that), but give their own instance of it a generator that writes
what Hardcharger's DuckDB 2.0 accepts where it differs from older DuckDB.
"""

from __future__ import annotations

from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.dialects.duckdb import DuckDB


class HardchargerDuckDBGenerator(DuckDB.Generator):  # type: ignore[valid-type,misc]
    def lambda_sql(self, expression: exp.Lambda, arrow_sep: str = "->", wrap: bool = True) -> str:
        # DuckDB 2.0 refuses the single-arrow lambda (`x -> x + 1`, deprecated since 1.3) with a
        # Binder Error; write the keyword form it accepts, `LAMBDA x : x + 1`
        # (`LAMBDA x, i : ...` for two arguments). sqlglot also builds lambdas of its own while
        # generating (array_compact, filter, transform, ...), which is why this is done here,
        # not on the expression tree.
        expression = expression.copy()
        expression.set("colon", True)
        return super().lambda_sql(expression, arrow_sep=arrow_sep, wrap=wrap)


def for_hardcharger(dialect: Dialect) -> Dialect:
    """``dialect`` itself, writing SQL Hardcharger's DuckDB 2.0 accepts if it is a ``duckdb``
    dialect instance (sqlglot makes a new instance per lookup, so no other session shares it)."""
    if isinstance(dialect, DuckDB):
        dialect.generator_class = HardchargerDuckDBGenerator
    return dialect
