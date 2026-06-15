"""bt-df-lkhouse-fw — Schema Evolution Engine.
Detects drift, applies allowed changes, blocks breaking changes."""
from engine.base import log
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import lit


class SchemaEvolver:
    def __init__(self, spark: SparkSession, table_config: dict):
        self.spark = spark
        self.config = table_config
        self.allowed = table_config.get("schema_evolution", {}).get("allowed", [])
        self.blocked = table_config.get("schema_evolution", {}).get("blocked", [])

    def detect_changes(self, df: DataFrame, table_full: str) -> dict:
        """Compare incoming DataFrame schema with existing table schema."""
        existing_df = self.spark.read.table(table_full)
        existing_cols = {f.name: f.dataType.simpleString() for f in existing_df.schema.fields}
        incoming_cols = {f.name: f.dataType.simpleString() for f in df.schema.fields}

        changes = {
            "add_columns": {},
            "type_changes": {},
            "dropped_columns": [],
        }

        for col, dtype in incoming_cols.items():
            if col not in existing_cols:
                changes["add_columns"][col] = dtype

        for col in incoming_cols:
            if col in existing_cols and incoming_cols[col] != existing_cols[col]:
                changes["type_changes"][col] = {
                    "from": existing_cols[col],
                    "to": incoming_cols[col]
                }

        for col in existing_cols:
            if col not in incoming_cols and col != "ingestion_ts":
                changes["dropped_columns"].append(col)

        return changes

    def apply_evolution(self, df: DataFrame, table_full: str) -> DataFrame:
        """Apply allowed schema changes, block disallowed ones."""
        changes = self.detect_changes(df, table_full)

        if not any(changes.values()):
            log("schema", "No schema changes detected")
            return df

        log("schema", f"Changes detected: {changes}")

        if changes["add_columns"]:
            if "add_column" in self.allowed:
                for col_name, col_type in changes["add_columns"].items():
                    log("schema", f"✅ ALLOWED: Adding column '{col_name}' ({col_type})")
                    self.spark.sql(f"ALTER TABLE {table_full} ADD COLUMNS ({col_name} {col_type})")
            else:
                blocked_cols = list(changes["add_columns"].keys())
                log("schema", f"🚫 BLOCKED: Cannot add columns {blocked_cols}")
                raise RuntimeError(f"Schema change blocked: add_column not allowed. Columns: {blocked_cols}")

        if changes["type_changes"]:
            for col, change in changes["type_changes"].items():
                is_widen = self._is_type_widening(change["from"], change["to"])
                if is_widen and "type_widen" in self.allowed:
                    log("schema", f"✅ ALLOWED: Type widening '{col}' ({change['from']} → {change['to']})")
                elif not is_widen and "type_narrow" in self.blocked:
                    log("schema", f"🚫 BLOCKED: Type narrowing '{col}' ({change['from']} → {change['to']})")
                    raise RuntimeError(f"Schema change blocked: type narrowing on '{col}'")

        if changes["dropped_columns"]:
            if "drop_column" in self.blocked:
                log("schema", f"🚫 BLOCKED: Cannot drop columns {changes['dropped_columns']}")
                raise RuntimeError(f"Schema change blocked: drop_column. Columns: {changes['dropped_columns']}")

        return df

    def align_dataframe(self, df: DataFrame, table_full: str) -> DataFrame:
        """Align DataFrame columns to match table schema (order + missing cols as NULL)."""
        table_cols = self.spark.read.table(table_full).columns

        for col in table_cols:
            if col not in df.columns:
                df = df.withColumn(col, lit(None))

        return df.select(*table_cols)

    def _is_type_widening(self, from_type: str, to_type: str) -> bool:
        widen_map = {
            ("int", "bigint"): True,
            ("int", "double"): True,
            ("bigint", "double"): True,
            ("float", "double"): True,
        }
        return widen_map.get((from_type, to_type), False)
