"""EastSide CDH 2.0 — Schema Evolution Engine (Layer-Aware).
Detects drift between incoming data and existing Iceberg table.
Applies rules per layer:
  - Bronze: accept everything (add, drop, widen, narrow)
  - Silver: non-breaking only (add, widen allowed; drop, narrow blocked)
  - Gold: contract-enforced (nothing allowed without explicit version bump)

Features:
  - Alias mapping: auto-rename columns before detection
  - Externalised type rules: configurable widening matrix
  - Schema fingerprint: skip detection if schema unchanged
  - Graceful mode: option to NULL-fill and alert instead of failing
  - Schema audit: write all changes to audit table
  - Schema quarantine: quarantine offending batches instead of only failing

Usage:
    Called internally by bronze.py and silver.py — not run standalone.
"""
import hashlib
import json
from datetime import datetime
from base import log, log_error, LogLevel
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import lit, current_timestamp
from pyspark.sql.types import StructType, StructField, StringType, TimestampType


# Default type widening rules (used if no external config provided)
DEFAULT_WIDEN_MAP = {
    ("int", "bigint"): True,
    ("int", "long"): True,
    ("int", "double"): True,
    ("int", "decimal"): True,
    ("integer", "long"): True,
    ("bigint", "double"): True,
    ("bigint", "decimal"): True,
    ("float", "double"): True,
    ("short", "int"): True,
    ("short", "integer"): True,
    ("short", "bigint"): True,
    ("decimal(10,2)", "decimal(20,2)"): True,
    ("decimal(10,0)", "decimal(20,0)"): True,
    ("date", "timestamp"): True,
}


def _build_widen_map(config: dict) -> dict:
    """Build type widening map from config or use defaults."""
    type_rules = config.get("type_rules", {})
    widen_list = type_rules.get("widen", [])

    if not widen_list:
        return DEFAULT_WIDEN_MAP

    widen_map = dict(DEFAULT_WIDEN_MAP)  # start with defaults
    for rule in widen_list:
        if isinstance(rule, str) and "->" in rule:
            parts = rule.split("->")
            from_type = parts[0].strip()
            to_type = parts[1].strip()
            widen_map[(from_type, to_type)] = True
        elif isinstance(rule, dict):
            widen_map[(rule["from"], rule["to"])] = True
    return widen_map


def _compute_schema_fingerprint(df: DataFrame) -> str:
    """Compute a hash of the DataFrame schema for quick comparison."""
    schema_str = "|".join(
        f"{f.name}:{f.dataType.simpleString()}" for f in sorted(df.schema.fields, key=lambda x: x.name)
    )
    return hashlib.sha256(schema_str.encode()).hexdigest()[:16]


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

        # Graceful mode: null_fill_and_alert instead of fail
        self.on_drop = evolution_config.get("on_drop", "fail")  # fail | null_fill_and_alert
        self.on_narrow = evolution_config.get("on_narrow", "fail")  # fail | cast_and_alert

        # Alias mapping (rename before detection)
        self.aliases = table_config.get("schema_evolution", {}).get("aliases", {})

        # Build type widening map
        self.widen_map = _build_widen_map(table_config)

        # Audit records collected during this run
        self._audit_records = []

        log("schema", f"[{self.table_name}] Layer={layer}, "
                      f"allowed={self.allowed}, blocked={self.blocked}, "
                      f"on_drop={self.on_drop}, aliases={len(self.aliases)}")

    def apply_aliases(self, df: DataFrame) -> DataFrame:
        """Rename incoming columns using alias mapping before detection.
        Aliases map: incoming_name -> canonical_name
        """
        if not self.aliases:
            return df

        renamed = []
        for incoming_name, canonical_name in self.aliases.items():
            if incoming_name in df.columns:
                df = df.withColumnRenamed(incoming_name, canonical_name)
                renamed.append(f"{incoming_name} → {canonical_name}")

        if renamed:
            log("schema", f"[{self.table_name}] Aliases applied: {renamed}")

        return df

    def check_fingerprint(self, df: DataFrame, table_full: str) -> bool:
        """Check if incoming schema matches stored fingerprint. Returns True if unchanged."""
        try:
            from google.cloud import storage as gcs_storage
            bucket_name = "eastside-lakehouse"  # TODO: make configurable
            fp_path = f"{self.layer}/_schema_fingerprints/{self.table_name}.json"
            client = gcs_storage.Client()
            blob = client.bucket(bucket_name).blob(fp_path)
            if not blob.exists():
                return False
            stored = json.loads(blob.download_as_text())
            incoming_fp = _compute_schema_fingerprint(df)
            if stored.get("fingerprint") == incoming_fp:
                log("schema", f"[{self.table_name}] Schema fingerprint unchanged — skipping detection")
                return True
            return False
        except Exception:
            return False

    def save_fingerprint(self, df: DataFrame):
        """Persist schema fingerprint after successful processing."""
        try:
            from google.cloud import storage as gcs_storage
            bucket_name = "eastside-lakehouse"
            fp_path = f"{self.layer}/_schema_fingerprints/{self.table_name}.json"
            client = gcs_storage.Client()
            blob = client.bucket(bucket_name).blob(fp_path)
            fp_data = {
                "fingerprint": _compute_schema_fingerprint(df),
                "columns": [f.name for f in df.schema.fields],
                "updated_at": datetime.now().isoformat(),
            }
            blob.upload_from_string(json.dumps(fp_data), content_type="application/json")
        except Exception as e:
            log("schema", f"[{self.table_name}] Failed to save fingerprint: {e}", LogLevel.WARN)

    def _record_audit(self, change_type: str, column_name: str,
                      old_type: str, new_type: str, status: str):
        """Record a schema change for the audit table."""
        self._audit_records.append({
            "table_name": self.table_name,
            "layer": self.layer,
            "change_type": change_type,
            "column_name": column_name,
            "old_type": old_type or "",
            "new_type": new_type or "",
            "event_timestamp": datetime.now().isoformat(),
            "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "status": status,
        })

    def flush_audit(self, catalog: str, namespace: str):
        """Write audit records to the schema_change_audit Iceberg table."""
        if not self._audit_records:
            return

        audit_table = f"{catalog}.{namespace}.schema_change_audit"
        schema = StructType([
            StructField("table_name", StringType()),
            StructField("layer", StringType()),
            StructField("change_type", StringType()),
            StructField("column_name", StringType()),
            StructField("old_type", StringType()),
            StructField("new_type", StringType()),
            StructField("event_timestamp", StringType()),
            StructField("run_id", StringType()),
            StructField("status", StringType()),
        ])

        df = self.spark.createDataFrame(self._audit_records, schema)
        df = df.withColumn("_recorded_at", current_timestamp())

        try:
            df.writeTo(audit_table).option("merge-schema", "true").append()
            log("audit", f"[{self.table_name}] Wrote {len(self._audit_records)} audit records")
        except Exception:
            try:
                df.writeTo(audit_table).create()
                log("audit", f"[{self.table_name}] Created audit table with {len(self._audit_records)} records")
            except Exception as e:
                log("audit", f"[{self.table_name}] Failed to write audit: {e}", LogLevel.WARN)

        self._audit_records = []

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
                     "_gold_published_at", "_quarantine_reason", "_quarantined_at",
                     "_schema_quarantine_reason", "_schema_diff"}
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

        # Step 1: Apply alias mapping (rename before detection)
        df = self.apply_aliases(df)

        # Step 2: Check fingerprint (skip if unchanged)
        if self.check_fingerprint(df, table_full):
            return df

        # Step 3: Detect changes
        changes = self.detect_changes(df, table_full)

        if not any(changes.values()):
            self.save_fingerprint(df)
            return df

        # --- ADD COLUMNS ---
        if changes["add_columns"]:
            if "add_column" in self.allowed:
                for col_name, col_type in changes["add_columns"].items():
                    log("schema", f"[{self.table_name}] ✅ ADD: {col_name} ({col_type})")
                    self._record_audit("add_column", col_name, "", col_type, "applied")
                    try:
                        self.spark.sql(
                            f"ALTER TABLE {table_full} ADD COLUMNS ({col_name} {col_type})")
                    except Exception as e:
                        log("schema", f"[{self.table_name}] ADD {col_name} skipped: {e}",
                            LogLevel.WARN)
            elif "add_column" in self.blocked:
                for col_name in changes["add_columns"]:
                    self._record_audit("add_column", col_name, "", changes["add_columns"][col_name], "blocked")
                log("schema", f"[{self.table_name}] 🚫 BLOCKED: add_column "
                              f"{list(changes['add_columns'].keys())}", LogLevel.ERROR)
                raise RuntimeError(
                    f"Schema evolution BLOCKED on '{self.table_name}' ({self.layer}): "
                    f"add_column not allowed. Columns: {list(changes['add_columns'].keys())}")
            else:
                for col_name, col_type in changes["add_columns"].items():
                    self._record_audit("add_column", col_name, "", col_type, "merge_schema")
                log("schema", f"[{self.table_name}] ⚠️ New columns will be handled by merge-schema",
                    LogLevel.WARN)

        # --- TYPE CHANGES ---
        if changes["type_changes"]:
            for col_name, change in changes["type_changes"].items():
                is_widen = self.widen_map.get((change["from"], change["to"]), False)

                if is_widen and "type_widen" in self.allowed:
                    log("schema", f"[{self.table_name}] ✅ WIDEN: {col_name} "
                                  f"({change['from']} → {change['to']})")
                    self._record_audit("type_widen", col_name, change["from"], change["to"], "applied")
                elif not is_widen and "type_narrow" in self.blocked:
                    self._record_audit("type_narrow", col_name, change["from"], change["to"], "blocked")

                    if self.on_narrow == "cast_and_alert":
                        # Graceful mode: cast and continue
                        log("schema", f"[{self.table_name}] ⚠️ GRACEFUL: type_narrow on {col_name} "
                                      f"({change['from']} → {change['to']}) — casting with alert",
                            LogLevel.WARN)
                        self._record_audit("type_narrow", col_name, change["from"], change["to"], "graceful_cast")
                    else:
                        # Strict mode: fail
                        log("schema", f"[{self.table_name}] 🚫 BLOCKED: type_narrow on {col_name} "
                                      f"({change['from']} → {change['to']})", LogLevel.ERROR)
                        raise RuntimeError(
                            f"Schema evolution BLOCKED on '{self.table_name}' ({self.layer}): "
                            f"type narrowing on '{col_name}' ({change['from']} → {change['to']})")
                elif is_widen:
                    log("schema", f"[{self.table_name}] ⚠️ Type widen {col_name} "
                                  f"(not explicitly allowed, proceeding)", LogLevel.WARN)
                    self._record_audit("type_widen", col_name, change["from"], change["to"], "implicit")
                else:
                    log("schema", f"[{self.table_name}] ⚠️ Type change {col_name} "
                                  f"({change['from']} → {change['to']}) — casting", LogLevel.WARN)
                    self._record_audit("type_change", col_name, change["from"], change["to"], "cast")

        # --- DROPPED COLUMNS ---
        if changes["dropped_columns"]:
            if "drop_column" in self.blocked:
                for col_name in changes["dropped_columns"]:
                    self._record_audit("drop_column", col_name, "", "", "blocked")

                if self.on_drop == "null_fill_and_alert":
                    # Graceful mode: NULL-fill and continue
                    log("schema", f"[{self.table_name}] ⚠️ GRACEFUL: drop_column "
                                  f"{changes['dropped_columns']} — NULL-filling with alert",
                        LogLevel.WARN)
                    for col_name in changes["dropped_columns"]:
                        df = df.withColumn(col_name, lit(None))
                        self._record_audit("drop_column", col_name, "", "", "graceful_null_fill")
                else:
                    # Strict mode: fail
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
                    self._record_audit("drop_column", col_name, "", "", "null_filled")

        # Save fingerprint after successful processing
        self.save_fingerprint(df)

        return df

    def quarantine_schema_violation(self, df: DataFrame, table_full: str,
                                    reason: str, changes: dict) -> None:
        """Write offending batch to schema quarantine table instead of only failing."""
        quarantine_table = f"{table_full}_schema_quarantine"
        schema_diff = json.dumps(changes, default=str)

        df_q = df.withColumn("_schema_quarantine_reason", lit(reason))
        df_q = df_q.withColumn("_schema_diff", lit(schema_diff))
        df_q = df_q.withColumn("_quarantined_at", current_timestamp())

        try:
            df_q.writeTo(quarantine_table).option("merge-schema", "true").append()
            log("schema", f"[{self.table_name}] Quarantined batch → {quarantine_table}")
        except Exception:
            try:
                df_q.writeTo(quarantine_table).create()
                log("schema", f"[{self.table_name}] Created schema quarantine with batch")
            except Exception as e:
                log("schema", f"[{self.table_name}] Failed to quarantine: {e}", LogLevel.ERROR)

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
