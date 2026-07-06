"""EastSide CDH 2.0 — Schema Evolution Engine (Layer-Aware).
Detects drift between incoming data and existing Iceberg table.
Applies rules per layer:
  - Bronze: accept everything (add, drop, widen, narrow)
  - Silver: non-breaking only (add, widen allowed; drop, narrow blocked)
  - Gold: contract-enforced (nothing allowed without explicit version bump)

Usage:
    Called internally by bronze.py and silver.py — not run standalone.
"""
from eastside.engine.base import log, log_error, LogLevel
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import lit


# Type widening rules (safe promotions)
WIDEN_MAP = {
    ("int", "bigint"): True,
    ("int", "double"): True,
    ("bigint", "double"): True,
    ("float", "double"): True,
    ("int", "long"): True,
    ("integer", "long"): True,
    ("short", "int"): True,
    ("short", "integer"): True,
}


class SchemaEvolver:
    """Layer-aware schema evolution for Iceberg tables."""

    def __init__(self, spark: SparkSession, table_config: dict, layer: str):
        """
        Args:
            spark: SparkSession
            table_config: table YAML config dict
            layer: one of 'bronze', 'silver', 'gold'
        """
        self.spark = spark
        self.config = table_config
        self.table_name = table_config.get("table", "unknown")
        self.layer = layer

        # Get layer-specific rules from config
        evolution_config = table_config.get("schema_evolution", {}).get(layer, {})
        self.allowed = evolution_config.get("allowed", [])
        self.blocked = evolution_config.get("blocked", [])

        log("schema", f"[{self.table_name}] Layer={layer}, "
                      f"allowed={self.allowed}, blocked={self.blocked}")

    def detect_changes(self, df: DataFrame, table_full: str) -> dict:
        """Compare incoming DataFrame schema with existing Iceberg table."""
        try:
            existing_df = self.spark.read.table(table_full)
        except Exception:
            log("schema", f"[{self.table_name}] Table does not exist — no evolution needed")
            return {"add_columns": {}, "type_changes": {}, "dropped_columns": []}

        existing_cols = {f.name: f.dataType.simpleString() for f in existing_df.schema.fields}
        incoming_cols = {f.name: f.dataType.simpleString() for f in df.schema.fields}

        changes = {"add_columns": {}, "type_changes": {}, "dropped_columns": []}

        # New columns in incoming
        for col_name, dtype in incoming_cols.items():
            if col_name not in existing_cols:
                changes["add_columns"][col_name] = dtype

        # Type changes
        for col_name in incoming_cols:
            if col_name in existing_cols and incoming_cols[col_name] != existing_cols[col_name]:
                changes["type_changes"][col_name] = {
                    "from": existing_cols[col_name],
                    "to": incoming_cols[col_name],
                }

        # Dropped columns (in existing but not in incoming)
        meta_cols = {"_ingested_at", "_source_file", "_batch_id", "_dq_flags",
                     "row_hash", "valid_from", "valid_to", "is_current",
                     "_gold_published_at", "_quarantine_reason", "_quarantined_at"}
        for col_name in existing_cols:
            if col_name not in incoming_cols and col_name not in meta_cols:
                changes["dropped_columns"].append(col_name)

        # Log detected changes
        if changes["add_columns"]:
            log("schema", f"[{self.table_name}] New columns: {list(changes['add_columns'].keys())}")
        if changes["type_changes"]:
            for c, ch in changes["type_changes"].items():
                log("schema", f"[{self.table_name}] Type change: {c} ({ch['from']} → {ch['to']})")
        if changes["dropped_columns"]:
            log("schema", f"[{self.table_name}] Dropped columns: {changes['dropped_columns']}")
        if not any(changes.values()):
            log("schema", f"[{self.table_name}] No schema changes detected")

        return changes

    def apply(self, df: DataFrame, table_full: str) -> DataFrame:
        """Apply schema evolution rules for this layer. Returns aligned DataFrame."""
        changes = self.detect_changes(df, table_full)

        if not any(changes.values()):
            return df

        # --- ADD COLUMNS ---
        if changes["add_columns"]:
            if "add_column" in self.allowed:
                for col_name, col_type in changes["add_columns"].items():
                    log("schema", f"[{self.table_name}] ✅ ADD: {col_name} ({col_type})")
                    try:
                        self.spark.sql(
                            f"ALTER TABLE {table_full} ADD COLUMNS ({col_name} {col_type})")
                    except Exception as e:
                        # Column might already exist from a previous run
                        log("schema", f"[{self.table_name}] ADD {col_name} skipped: {e}",
                            LogLevel.WARN)
            elif "add_column" in self.blocked:
                log("schema", f"[{self.table_name}] 🚫 BLOCKED: add_column "
                              f"{list(changes['add_columns'].keys())}", LogLevel.ERROR)
                raise RuntimeError(
                    f"Schema evolution BLOCKED on '{self.table_name}' ({self.layer}): "
                    f"add_column not allowed. Columns: {list(changes['add_columns'].keys())}")
            else:
                # Not explicitly allowed or blocked — warn and proceed (merge-schema handles it)
                log("schema", f"[{self.table_name}] ⚠️ New columns will be handled by merge-schema",
                    LogLevel.WARN)

        # --- TYPE CHANGES ---
        if changes["type_changes"]:
            for col_name, change in changes["type_changes"].items():
                is_widen = WIDEN_MAP.get((change["from"], change["to"]), False)

                if is_widen and "type_widen" in self.allowed:
                    log("schema", f"[{self.table_name}] ✅ WIDEN: {col_name} "
                                  f"({change['from']} → {change['to']})")
                elif not is_widen and "type_narrow" in self.blocked:
                    log("schema", f"[{self.table_name}] 🚫 BLOCKED: type_narrow on {col_name} "
                                  f"({change['from']} → {change['to']})", LogLevel.ERROR)
                    raise RuntimeError(
                        f"Schema evolution BLOCKED on '{self.table_name}' ({self.layer}): "
                        f"type narrowing on '{col_name}' ({change['from']} → {change['to']})")
                elif is_widen:
                    log("schema", f"[{self.table_name}] ⚠️ Type widen {col_name} "
                                  f"(not explicitly allowed, proceeding)", LogLevel.WARN)
                else:
                    log("schema", f"[{self.table_name}] ⚠️ Type change {col_name} "
                                  f"({change['from']} → {change['to']}) — casting", LogLevel.WARN)

        # --- DROPPED COLUMNS ---
        if changes["dropped_columns"]:
            if "drop_column" in self.blocked:
                log("schema", f"[{self.table_name}] 🚫 BLOCKED: drop_column "
                              f"{changes['dropped_columns']}", LogLevel.ERROR)
                raise RuntimeError(
                    f"Schema evolution BLOCKED on '{self.table_name}' ({self.layer}): "
                    f"drop_column blocked. Missing: {changes['dropped_columns']}")
            else:
                # Accept — fill missing columns with NULL
                log("schema", f"[{self.table_name}] ⚠️ Dropped columns (NULL-filled): "
                              f"{changes['dropped_columns']}", LogLevel.WARN)
                for col_name in changes["dropped_columns"]:
                    df = df.withColumn(col_name, lit(None))

        return df

    def align_to_table(self, df: DataFrame, table_full: str) -> DataFrame:
        """Align DataFrame columns to match existing table schema (order + missing as NULL)."""
        try:
            table_cols = self.spark.read.table(table_full).columns
        except Exception:
            return df  # New table, no alignment needed

        # Add any missing columns as NULL
        for col_name in table_cols:
            if col_name not in df.columns:
                df = df.withColumn(col_name, lit(None))

        # Select in table column order (only columns that exist in table)
        # Plus any new columns from incoming
        existing_set = set(table_cols)
        new_cols = [c for c in df.columns if c not in existing_set]
        select_order = table_cols + new_cols

        return df.select(*[c for c in select_order if c in df.columns])
