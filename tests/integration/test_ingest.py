"""Integration tests for HardchargerSession.ingest() (bulk Arrow/pandas loading)."""

import pyarrow as pa
import pytest


class TestIngest:
    """Tests for bulk-loading data via session.ingest()."""

    def test_ingest_create_from_arrow_table(self, session):
        """Test ingesting a pyarrow.Table with mode='create'."""
        table_name = "ingest_create_arrow"
        arrow_table = pa.table(data={"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})

        df = session.ingest(table_name=table_name, data=arrow_table, mode="create")
        result = sorted(df.collect(), key=lambda row: row.id)

        assert len(result) == 3
        assert result[0].id == 1
        assert result[0].name == "Alice"

    def test_ingest_keeps_column_case(self, session):
        """The DataFrame over the ingested table shows its columns as the data spelled them."""
        arrow_table = pa.table(data={"UPPER_NAME": [1], "MixedCase": ["a"], "lower_name": [True]})

        df = session.ingest(table_name="ingest_column_case", data=arrow_table, mode="create")

        assert df.columns == ["UPPER_NAME", "MixedCase", "lower_name"]
        assert df.collect()[0].asDict() == {"UPPER_NAME": 1, "MixedCase": "a", "lower_name": True}
        assert df.filter("upper_name = 1").columns == df.columns

    def test_ingest_append(self, session):
        """Test that mode='append' accumulates rows across calls."""
        table_name = "ingest_append"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1, 2]}), mode="create")
        df = session.ingest(table_name=table_name, data=pa.table(data={"id": [3, 4]}), mode="append")

        assert df.count() == 4

    def test_ingest_replace(self, session):
        """Test that mode='replace' drops existing rows before loading."""
        table_name = "ingest_replace"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1, 2, 3]}), mode="create")
        df = session.ingest(table_name=table_name, data=pa.table(data={"id": [9]}), mode="replace")

        result = df.collect()
        assert len(result) == 1
        assert result[0].id == 9

    def test_ingest_from_pandas_dataframe(self, session):
        """Test ingesting a pandas.DataFrame."""
        pd = pytest.importorskip("pandas")
        table_name = "ingest_pandas"
        pandas_df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})

        df = session.ingest(table_name=table_name, data=pandas_df, mode="create")
        result = sorted(df.collect(), key=lambda row: row.id)

        assert len(result) == 2
        assert result[0].name == "Alice"

    def test_ingest_create_errors_if_table_exists(self, session):
        """Test that mode='create' against an existing table raises."""
        table_name = "ingest_create_conflict"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1]}), mode="create")

        with pytest.raises(Exception):
            session.ingest(table_name=table_name, data=pa.table(data={"id": [2]}), mode="create")

    def test_ingest_large_table_streams_in_many_batches(self, session):
        """A ~24 MB table goes up as several record batches (spread over the
        driver's parallel ingest parts), and every row lands exactly once."""
        table_name = "ingest_large"
        n = 40
        payload = "x" * 600_000
        table = pa.table(data={"id": list(range(n)), "payload": [payload] * n})
        assert table.nbytes > 16 * 1024 * 1024

        df = session.ingest(table_name=table_name, data=table, mode="create")

        assert df.count() == n
        rows = session.sql(
            f"SELECT count(DISTINCT id) AS ids, sum(length(payload)) AS chars FROM {table_name}"
        ).collect()
        assert (rows[0].ids, rows[0].chars) == (n, n * len(payload))

    def test_ingest_append_large_table(self, session):
        table_name = "ingest_append_large"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [0], "payload": ["seed"]}), mode="create")
        n = 40
        table = pa.table(data={"id": list(range(1, n + 1)), "payload": ["x" * 600_000] * n})

        df = session.ingest(table_name=table_name, data=table, mode="append")

        assert df.count() == n + 1

    def test_ingest_create_append_and_temporary(self, session):
        table_name = "ingest_create_append_tmp"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1]}), mode="create_append", temporary=True)
        df = session.ingest(
            table_name=table_name, data=pa.table(data={"id": [2]}), mode="create_append", temporary=True
        )

        assert sorted(row.id for row in df.collect()) == [1, 2]
        cursor = session._cur
        cursor.execute(f"SELECT database_name FROM duckdb_tables() WHERE table_name = '{table_name}'")
        assert cursor.fetchall() == [("temp",)]

    def test_ingest_parts_one_keeps_row_order(self, session):
        """ingest_parts=1 sends one ordered stream: the table reads back in the
        order it was sent, even across many batches."""
        table_name = "ingest_ordered"
        n = 200_000
        table = pa.table(data={"i": list(range(n))})
        reader = pa.RecordBatchReader.from_batches(schema=table.schema, batches=table.to_batches(max_chunksize=5_000))

        df = session.ingest(table_name=table_name, data=reader, mode="create", ingest_parts=1)

        assert df.toArrow().column("i").to_pylist() == list(range(n))

    def test_failed_append_leaves_the_table_unchanged(self, session):
        """An ingest is one transaction: a stream that fails part-way leaves
        none of its rows behind (what the GizmoSQL version needed a staging
        table for)."""
        table_name = "ingest_atomic"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1, 2, 3]}), mode="create")
        schema = pa.schema([pa.field("id", pa.int64())])

        def batches():
            for start in range(0, 50_000, 5_000):
                yield pa.record_batch([pa.array(range(start, start + 5_000), type=pa.int64())], schema=schema)
            raise ValueError("the source failed part-way")

        with pytest.raises(Exception) as excinfo:
            session.ingest(
                table_name=table_name,
                data=pa.RecordBatchReader.from_batches(schema=schema, batches=batches()),
                mode="append",
            )
        assert "the source failed part-way" in str(excinfo.value)
        assert session.sql(f"SELECT count(*) AS n FROM {table_name}").collect()[0].n == 3

    def test_ingest_replace_with_other_columns(self, session):
        """The returned DataFrame has the replaced table's columns, not the old ones."""
        table_name = "ingest_replace_columns"
        session.ingest(table_name=table_name, data=pa.table(data={"id": [1]}), mode="create")
        df = session.ingest(table_name=table_name, data=pa.table(data={"code": ["a"], "n": [2]}), mode="replace")

        assert df.columns == ["code", "n"]
        assert df.collect()[0].asDict() == {"code": "a", "n": 2}

    def test_ingested_dataframe_works_as_a_temp_view(self, session):
        df = session.ingest(
            table_name="ingest_view_source", data=pa.table(data={"id": [1, 2], "v": ["a", "b"]}), mode="replace"
        )
        df.createOrReplaceTempView("ingest_view")

        rows = session.sql("SELECT v FROM ingest_view WHERE id = 2").collect()
        assert [row.v for row in rows] == ["b"]
