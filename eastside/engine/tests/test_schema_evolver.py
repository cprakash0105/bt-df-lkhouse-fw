"""Unit tests for SchemaEvolver — runs locally without Spark or GCS.

Tests:
  - detect_changes: new column, dropped column, type change, no change, table not exist
  - apply: bronze always runs ALTER TABLE, silver respects config
  - check_fingerprint: forces detection when Iceberg table is missing columns
  - align_to_table: includes columns added via ALTER TABLE this run

Run:
    pip install pytest
    pytest eastside/engine/tests/test_schema_evolver.py -v
"""
import sys
import types
import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs — lets schema_evolver.py import without pyspark or GCS
# ---------------------------------------------------------------------------

def _stub_pyspark():
    pyspark = types.ModuleType("pyspark")
    sql = types.ModuleType("pyspark.sql")
    funcs = types.ModuleType("pyspark.sql.functions")
    typs = types.ModuleType("pyspark.sql.types")

    funcs.lit = lambda v: v
    funcs.current_timestamp = lambda: None

    class StringType: pass
    class TimestampType: pass
    class StructField:
        def __init__(self, name, dtype, *a, **kw): self.name = name
    class StructType:
        def __init__(self, fields=None): self.fields = fields or []

    typs.StringType = StringType
    typs.TimestampType = TimestampType
    typs.StructField = StructField
    typs.StructType = StructType

    class SparkSession: pass
    class DataFrame: pass
    sql.SparkSession = SparkSession
    sql.DataFrame = DataFrame
    pyspark.sql = sql

    for name, mod in [("pyspark", pyspark), ("pyspark.sql", sql),
                      ("pyspark.sql.functions", funcs), ("pyspark.sql.types", typs)]:
        sys.modules[name] = mod


def _stub_base():
    base = types.ModuleType("base")
    base.log = lambda *a, **kw: None
    base.log_error = lambda *a, **kw: None
    class LogLevel:
        INFO = "INFO"; WARN = "WARN"; ERROR = "ERROR"
    base.LogLevel = LogLevel
    sys.modules["base"] = base


_stub_pyspark()
_stub_base()

sys.path.insert(0, "eastside/engine")
from schema_evolver import SchemaEvolver, _compute_schema_fingerprint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(name, type_str):
    f = MagicMock()
    f.name = name
    f.dataType.simpleString.return_value = type_str
    return f


def _df(columns: dict):
    """Build a fake DataFrame with given {name: type} columns."""
    df = MagicMock()
    df.columns = list(columns.keys())
    df.schema.fields = [_field(n, t) for n, t in columns.items()]
    df.withColumn = lambda name, val: df
    df.withColumnRenamed = lambda old, new: df
    df.select = MagicMock(return_value=MagicMock())
    return df


def _spark(existing: dict = None):
    """Build a fake SparkSession. existing=None means table doesn't exist."""
    spark = MagicMock()
    if existing is None:
        spark.read.table.side_effect = Exception("Table not found")
    else:
        spark.read.table.return_value = _df(existing)
    spark.sql = MagicMock()
    return spark


def _evolver(spark, layer="bronze", config=None):
    cfg = config or {"table": "sensor_data"}
    with patch.object(SchemaEvolver, "check_fingerprint", return_value=False), \
         patch.object(SchemaEvolver, "save_fingerprint"):
        return SchemaEvolver(spark, cfg, layer)


# ---------------------------------------------------------------------------
# detect_changes
# ---------------------------------------------------------------------------

class TestDetectChanges:

    def test_detects_new_column(self):
        spark = _spark({"sensor_id": "string", "temperature": "double"})
        ev = _evolver(spark)
        incoming = _df({"sensor_id": "string", "temperature": "double", "humidity": "double"})
        changes = ev.detect_changes(incoming, "cat.bronze.sensor_data")
        assert "humidity" in changes["add_columns"]

    def test_no_changes(self):
        cols = {"sensor_id": "string", "temperature": "double"}
        spark = _spark(cols)
        ev = _evolver(spark)
        changes = ev.detect_changes(_df(cols), "cat.bronze.sensor_data")
        assert not any(changes.values())

    def test_detects_dropped_column(self):
        spark = _spark({"sensor_id": "string", "temperature": "double", "humidity": "double"})
        ev = _evolver(spark)
        incoming = _df({"sensor_id": "string", "temperature": "double"})
        changes = ev.detect_changes(incoming, "cat.bronze.sensor_data")
        assert "humidity" in changes["dropped_columns"]

    def test_detects_type_change(self):
        spark = _spark({"sensor_id": "string", "temperature": "int"})
        ev = _evolver(spark)
        incoming = _df({"sensor_id": "string", "temperature": "double"})
        changes = ev.detect_changes(incoming, "cat.bronze.sensor_data")
        assert changes["type_changes"]["temperature"] == {"from": "int", "to": "double"}

    def test_table_not_exist_returns_empty(self):
        spark = _spark(None)
        ev = _evolver(spark)
        changes = ev.detect_changes(_df({"sensor_id": "string"}), "cat.bronze.sensor_data")
        assert changes == {"add_columns": {}, "type_changes": {}, "dropped_columns": []}

    def test_meta_columns_not_flagged_as_dropped(self):
        spark = _spark({"sensor_id": "string", "_ingested_at": "timestamp", "row_hash": "string"})
        ev = _evolver(spark)
        incoming = _df({"sensor_id": "string"})
        changes = ev.detect_changes(incoming, "cat.bronze.sensor_data")
        assert "_ingested_at" not in changes["dropped_columns"]
        assert "row_hash" not in changes["dropped_columns"]


# ---------------------------------------------------------------------------
# apply — bronze always runs ALTER TABLE regardless of config
# ---------------------------------------------------------------------------

class TestApply:

    def test_bronze_runs_alter_table_for_new_column(self):
        spark = _spark({"sensor_id": "string", "temperature": "double"})
        ev = _evolver(spark, layer="bronze")
        incoming = _df({"sensor_id": "string", "temperature": "double", "humidity": "double"})

        with patch.object(ev, "check_fingerprint", return_value=False), \
             patch.object(ev, "save_fingerprint"):
            ev.apply(incoming, "cat.bronze.sensor_data")

        spark.sql.assert_called_once_with(
            "ALTER TABLE cat.bronze.sensor_data ADD COLUMNS (humidity double)"
        )

    def test_bronze_no_alter_when_no_new_columns(self):
        cols = {"sensor_id": "string", "temperature": "double"}
        spark = _spark(cols)
        ev = _evolver(spark, layer="bronze")

        with patch.object(ev, "check_fingerprint", return_value=False), \
             patch.object(ev, "save_fingerprint"):
            ev.apply(_df(cols), "cat.bronze.sensor_data")

        spark.sql.assert_not_called()

    def test_silver_no_config_does_not_alter(self):
        spark = _spark({"sensor_id": "string"})
        ev = _evolver(spark, layer="silver")
        incoming = _df({"sensor_id": "string", "humidity": "double"})

        with patch.object(ev, "check_fingerprint", return_value=False), \
             patch.object(ev, "save_fingerprint"):
            ev.apply(incoming, "cat.silver.sensor_data")

        spark.sql.assert_not_called()

    def test_silver_with_add_column_allowed_runs_alter(self):
        spark = _spark({"sensor_id": "string"})
        cfg = {"table": "sensor_data", "schema_evolution": {"silver": {"allowed": ["add_column"]}}}
        ev = _evolver(spark, layer="silver", config=cfg)
        incoming = _df({"sensor_id": "string", "humidity": "double"})

        with patch.object(ev, "check_fingerprint", return_value=False), \
             patch.object(ev, "save_fingerprint"):
            ev.apply(incoming, "cat.silver.sensor_data")

        spark.sql.assert_called_once()

    def test_last_add_columns_populated_after_apply(self):
        spark = _spark({"sensor_id": "string"})
        ev = _evolver(spark, layer="bronze")
        incoming = _df({"sensor_id": "string", "humidity": "double"})

        with patch.object(ev, "check_fingerprint", return_value=False), \
             patch.object(ev, "save_fingerprint"):
            ev.apply(incoming, "cat.bronze.sensor_data")

        assert "humidity" in ev._last_add_columns


# ---------------------------------------------------------------------------
# check_fingerprint — key scenario: stale fingerprint + missing column
# ---------------------------------------------------------------------------

class TestCheckFingerprint:

    def test_forces_detection_when_table_missing_column(self):
        """Fingerprint may match incoming schema, but if Iceberg table is missing
        a column, detection must run — this was the root cause of the sensor_data bug."""
        incoming_cols = {"sensor_id": "string", "temperature": "double", "humidity": "double"}
        table_cols = {"sensor_id": "string", "temperature": "double"}  # humidity missing

        spark = _spark(table_cols)
        ev = _evolver(spark)
        incoming = _df(incoming_cols)

        # check_fingerprint should return False (force detection) because
        # humidity is in incoming but not in the Iceberg table
        result = ev.check_fingerprint(incoming, "cat.bronze.sensor_data")
        assert result is False

    def test_skips_when_table_has_all_columns_and_fp_matches(self):
        incoming_cols = {"sensor_id": "string", "temperature": "double"}
        spark = _spark(incoming_cols)  # table has same cols
        ev = _evolver(spark)
        incoming = _df(incoming_cols)

        # Build matching fingerprint
        fp = _compute_schema_fingerprint(incoming)
        stored = json.dumps({"fingerprint": fp})

        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_blob.download_as_text.return_value = stored

        mock_gcs = MagicMock()
        mock_gcs.Client.return_value.bucket.return_value.blob.return_value = mock_blob

        with patch.dict("sys.modules", {"google.cloud.storage": mock_gcs}):
            import importlib
            import schema_evolver as se
            original = getattr(se, "gcs_storage", None)
            se.gcs_storage = mock_gcs
            result = ev.check_fingerprint(incoming, "cat.bronze.sensor_data")
            if original:
                se.gcs_storage = original

        assert result is True


# ---------------------------------------------------------------------------
# align_to_table
# ---------------------------------------------------------------------------

class TestAlignToTable:

    def test_includes_alter_table_columns_not_in_cached_schema(self):
        """humidity was added via ALTER TABLE this run but spark.read.table
        still returns stale 2-column schema — align_to_table must include it."""
        stale_table_cols = {"sensor_id": "string", "temperature": "double"}
        spark = _spark(stale_table_cols)
        ev = _evolver(spark)
        ev._last_add_columns = {"humidity"}

        incoming = _df({"sensor_id": "string", "temperature": "double", "humidity": "double"})
        ev.align_to_table(incoming, "cat.bronze.sensor_data")

        call_args = incoming.select.call_args[0]
        assert "humidity" in call_args

    def test_table_not_exist_returns_df_unchanged(self):
        spark = _spark(None)
        ev = _evolver(spark)
        incoming = _df({"sensor_id": "string"})
        result = ev.align_to_table(incoming, "cat.bronze.sensor_data")
        assert result is incoming
