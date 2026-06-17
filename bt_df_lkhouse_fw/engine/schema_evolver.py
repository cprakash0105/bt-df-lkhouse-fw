"""bt-df-lkhouse-fw — Schema Evolution Engine.
Detects drift between incoming data and existing Iceberg table, applies allowed changes, blocks breaking ones."""
from bt_df_lkhouse_fw.engine.base import log, log_error, LogLevel
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import lit


class SchemaEvolver:
    def __init__(self, spark: SparkSession, table_config: dict):
        self.spark = spark
        self.config = table_config
        self.table_name = table_config.get("table", "unknown")
        self.allowed = table_config.get("schema_evolution", {}).get("allowed", [])
        self.blocked = table_config.get("schema_evolution", {}).get("blocked", [])
        log("schema", f"[{self.table_name}] Governance: allowed={self.allowed}, blocked={self.blocked}")

    def detect_changes(self, df: DataFrame, table_full: str) -> dict:
        """Compare incoming DataFrame schema with existing Iceberg table schema."""
        log("schema", f"[{self.table_name}] Detecting changes against: {table_full}")

        existing_df = self.spark.read.table(table_full)
        existing_cols = {f.name: f.dataType.simpleString() for f in existing_df.schema.fields}
        incoming_cols = {f.name: f.dataType.simpleString() for f in df.schema.fields}

        log("schema", f"[{self.table_name}] Existing ({len(existing_cols)}): {list(existing_cols.keys())}")
        log("schema", f"[{self.table_name}] Incoming ({len(incoming_cols)}): {list(incoming_cols.keys())}")

        changes = {"add_columns": {}, "type_changes": {}, "dropped_columns": []}

        for col_name, dtype in incoming_cols.items():
            if col_name not in existing_cols:
                changes["add_columns"][col_name] = dtype

        for col_name in incoming_cols:
            if col_name in existing_cols and incoming_cols[col_name] != existing_cols[col_name]:
                changes["type_changes"][col_name] = {
                    "from": existing_cols[col_name],
                    "to": incoming_cols[col_name],
                }

        for col_name in existing_cols:
            if col_name not in incoming_cols and col_name != "ingestion_ts":
                changes["dropped_columns"].append(col_name)

        # Log each detected change
        for col_name, col_type in changes["add_columns"].items():
            log("schema", f"[{self.table_name}] DETECTED: New column '{col_name}' ({col_type})")
        for col_name, change in changes["type_changes"].items():
            log("schema", f"[{self.table_name}] DETECTED: Type change '{col_name}' ({change['from']} → {change['to']})")
        for col_name in changes["dropped_columns"]:
            log("schema", f"[{self.table_name}] DETECTED: Dropped column '{col_name}'")

        if not any(changes.values()):
            log("schema", f"[{self.table_name}] No schema changes detected")

        return changes

    def apply_evolution(self, df: DataFrame, table_full: str) -> DataFrame:
        """Apply allowed schema changes, block disallowed ones."""
        changes = self.detect_changes(df, table_full)

        if not any(changes.values()):
            return df

        # ADD COLUMN
        if changes["add_columns"]:
            if "add_column" in self.allowed:
                for col_name, col_type in changes["add_columns"].items():
                    log("schema", f"[{self.table_name}] ✅ ALLOWED: Adding column '{col_name}' ({col_type})")
                    try:
                        self.spark.sql(f"ALTER TABLE {table_full} ADD COLUMNS ({col_name} {col_type})")
                    except Exception as e:
                        log_error("schema", f"[{self.table_name}] Failed to add column '{col_name}'", e)
                        raise
            else:
                blocked_cols = list(changes["add_columns"].keys())
                log("schema", f"[{self.table_name}] 🚫 BLOCKED: Cannot add columns {blocked_cols}", LogLevel.ERROR)
                raise RuntimeError(
                    f"Schema change BLOCKED on '{self.table_name}': "
                    f"add_column not allowed. Columns: {blocked_cols}"
                )

        # TYPE CHANGES
        if changes["type_changes"]:
            for col_name, change in changes["type_changes"].items():
                is_widen = self._is_type_widening(change["from"], change["to"])
                if is_widen and "type_widen" in self.allowed:
                    log("schema", f"[{self.table_name}] ✅ ALLOWED: Type widening '{col_name}' ({change['from']} → {change['to']})")
                elif not is_widen and "type_narrow" in self.blocked:
                    log("schema", f"[{self.table_name}] 🚫 BLOCKED: Type narrowing '{col_name}' ({change['from']} → {change['to']})", LogLevel.ERROR)
                    raise RuntimeError(
                        f"Schema change BLOCKED on '{self.table_name}': "
                        f"Type narrowing on '{col_name}' ({change['from']} → {change['to']})"
                    )
                else:
                    log("schema", f"[{self.table_name}] ⚠️  UNHANDLED: Type change '{col_name}'", LogLevel.WARN)

        # DROP COLUMN
        if changes["dropped_columns"]:
            if "drop_column" in self.blocked:
                log("schema", f"[{self.table_name}] 🚫 BLOCKED: Cannot drop columns {changes['dropped_columns']}", LogLevel.ERROR)
                raise RuntimeError(
                    f"Schema change BLOCKED on '{self.table_name}': "
                    f"drop_column blocked. Missing: {changes['dropped_columns']}"
                )
            else:
                log("schema", f"[{self.table_name}] ⚠️  Columns missing (will be NULL): {changes['dropped_columns']}", LogLevel.WARN)

        return df

    def align_dataframe(self, df: DataFrame, table_full: str) -> DataFrame:
        """Align DataFrame columns to match table schema (order + missing cols as NULL)."""
        table_cols = self.spark.read.table(table_full).columns
        added_nulls = []

        for col_name in table_cols:
            if col_name not in df.columns:
                df = df.withColumn(col_name, lit(None))
                added_nulls.append(col_name)

        if added_nulls:
            log("schema", f"[{self.table_name}] Aligned: added NULL for {added_nulls}")

        return df.select(*table_cols)

    def _is_type_widening(self, from_type: str, to_type: str) -> bool:
        widen_map = {
            ("int", "bigint"): True,
            ("int", "double"): True,
            ("bigint", "double"): True,
            ("float", "double"): True,
        }
        return widen_map.get((from_type, to_type), False)
