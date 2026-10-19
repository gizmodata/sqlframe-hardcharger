"""Unit tests for package imports."""


def test_import_main_package():
    """Test that the main package can be imported."""
    import sqlframe_hardcharger

    assert sqlframe_hardcharger is not None


def test_import_session():
    """Test that HardchargerSession can be imported."""
    from sqlframe_hardcharger import HardchargerSession

    assert HardchargerSession is not None
    assert hasattr(HardchargerSession, "builder")


def test_import_dataframe():
    """Test that DataFrame classes can be imported."""
    from sqlframe_hardcharger import (
        HardchargerDataFrame,
        HardchargerDataFrameNaFunctions,
        HardchargerDataFrameStatFunctions,
    )

    assert HardchargerDataFrame is not None
    assert HardchargerDataFrameNaFunctions is not None
    assert HardchargerDataFrameStatFunctions is not None


def test_import_catalog():
    """Test that HardchargerCatalog can be imported."""
    from sqlframe_hardcharger import HardchargerCatalog

    assert HardchargerCatalog is not None


def test_import_readwriter():
    """Test that reader/writer classes can be imported."""
    from sqlframe_hardcharger import HardchargerDataFrameReader, HardchargerDataFrameWriter

    assert HardchargerDataFrameReader is not None
    assert HardchargerDataFrameWriter is not None


def test_import_group():
    """Test that HardchargerGroupedData can be imported."""
    from sqlframe_hardcharger import HardchargerGroupedData

    assert HardchargerGroupedData is not None


def test_import_table():
    """Test that HardchargerTable can be imported."""
    from sqlframe_hardcharger import HardchargerTable

    assert HardchargerTable is not None


def test_import_udf():
    """Test that HardchargerUDFRegistration can be imported."""
    from sqlframe_hardcharger import HardchargerUDFRegistration

    assert HardchargerUDFRegistration is not None


def test_import_column():
    """Test that Column can be imported."""
    from sqlframe_hardcharger import Column

    assert Column is not None


def test_import_types():
    """Test that Row type can be imported."""
    from sqlframe_hardcharger import Row

    assert Row is not None


def test_import_window():
    """Test that Window classes can be imported."""
    from sqlframe_hardcharger import Window, WindowSpec

    assert Window is not None
    assert WindowSpec is not None


def test_import_functions():
    """Test that functions module can be imported."""
    from sqlframe_hardcharger import functions

    assert functions is not None
    # Test a few common functions
    assert hasattr(functions, "col")
    assert hasattr(functions, "lit")
    assert hasattr(functions, "sum")
    assert hasattr(functions, "count")


def test_import_activate():
    """Test that activate function can be imported."""
    from sqlframe_hardcharger import activate

    assert activate is not None
    assert callable(activate)


def test_all_exports():
    """Test that __all__ contains expected exports."""
    import sqlframe_hardcharger

    expected_exports = [
        "activate",
        "Column",
        "HardchargerCatalog",
        "HardchargerDataFrame",
        "HardchargerDataFrameNaFunctions",
        "HardchargerDataFrameReader",
        "HardchargerDataFrameStatFunctions",
        "HardchargerDataFrameWriter",
        "HardchargerGroupedData",
        "HardchargerSession",
        "HardchargerTable",
        "HardchargerUDFRegistration",
        "Row",
        "Window",
        "WindowSpec",
    ]

    for export in expected_exports:
        assert export in sqlframe_hardcharger.__all__, f"{export} not in __all__"
        assert hasattr(sqlframe_hardcharger, export), f"{export} not accessible"
