from __future__ import annotations

import typing as t

from sqlframe.base.udf import _BaseUDFRegistration

if t.TYPE_CHECKING:
    from sqlframe.base._typing import DataTypeOrString, UserDefinedFunctionLike

    from sqlframe_hardcharger.session import HardchargerSession  # noqa: F401


class HardchargerUDFRegistration(_BaseUDFRegistration["HardchargerSession"]):
    def register(
        self,
        name: str,
        f: t.Union[t.Callable[..., t.Any], UserDefinedFunctionLike],
        returnType: t.Optional[DataTypeOrString] = None,
    ) -> UserDefinedFunctionLike:
        # A Python UDF runs in the Python process that defines it; the
        # statements run on a remote Hardcharger server, which can't call back
        # into this client.
        raise NotImplementedError(
            "Python UDFs are not supported on Hardcharger: queries run on the server, which can't call "
            f"back into this Python process to run {name!r}. Express the logic with "
            "pyspark.sql.functions or in SQL instead."
        )
