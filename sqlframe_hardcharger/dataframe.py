from __future__ import annotations

import logging
import typing as t

import pyarrow
from sqlframe.base.dataframe import (
    BaseDataFrame,
    _BaseDataFrameNaFunctions,
    _BaseDataFrameStatFunctions,
)
from sqlframe.base.mixins.dataframe_mixins import (
    NoCachePersistSupportMixin,
    TypedColumnsFromTempViewMixin,
)

from sqlframe_hardcharger.group import HardchargerGroupedData

if t.TYPE_CHECKING:
    from sqlframe_hardcharger.session import HardchargerSession  # noqa
    from sqlframe_hardcharger.readwriter import HardchargerDataFrameWriter  # noqa
    from sqlframe_hardcharger.group import HardchargerGroupedData  # noqa
    from pyarrow import Table as ArrowTable, RecordBatchReader

logger = logging.getLogger(__name__)


class HardchargerDataFrameNaFunctions(_BaseDataFrameNaFunctions["HardchargerDataFrame"]):
    pass


class HardchargerDataFrameStatFunctions(_BaseDataFrameStatFunctions["HardchargerDataFrame"]):
    pass


class HardchargerDataFrame(
    NoCachePersistSupportMixin,
    TypedColumnsFromTempViewMixin,
    BaseDataFrame[
        "HardchargerSession",
        "HardchargerDataFrameWriter",
        "HardchargerDataFrameNaFunctions",
        "HardchargerDataFrameStatFunctions",
        "HardchargerGroupedData",
    ],
):
    _na = HardchargerDataFrameNaFunctions
    _stat = HardchargerDataFrameStatFunctions
    _group_data = HardchargerGroupedData

    def explain(
        self,
        extended: t.Optional[t.Union[bool, str]] = None,
        mode: t.Optional[str] = None,
    ) -> None:
        results = self._get_explain_plan_rows()
        print(results[0][1])

    @t.overload
    def toArrow(self) -> ArrowTable: ...

    @t.overload
    def toArrow(self, batch_size: int) -> RecordBatchReader: ...

    def toArrow(self, batch_size: t.Optional[int] = None) -> t.Union[ArrowTable, RecordBatchReader]:
        self._collect(skip_rows=True)
        if not batch_size:
            return self.session._last_result.fetch_arrow_table()
        table = self.session._last_result.fetch_arrow_table()
        batches = table.to_batches(max_chunksize=batch_size)
        return pyarrow.RecordBatchReader.from_batches(schema=table.schema, batches=batches)
