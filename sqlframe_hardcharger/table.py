from sqlframe.base.mixins.table_mixins import (
    DeleteSupportMixin,
    UpdateSupportMixin,
)
from sqlframe.base.table import _BaseTable

from sqlframe_hardcharger.dataframe import HardchargerDataFrame


class HardchargerTable(
    HardchargerDataFrame,
    UpdateSupportMixin["HardchargerDataFrame"],
    DeleteSupportMixin["HardchargerDataFrame"],
    _BaseTable["HardchargerDataFrame"],
):
    _df = HardchargerDataFrame
