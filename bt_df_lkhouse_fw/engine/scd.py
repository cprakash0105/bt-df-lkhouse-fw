"""bt-df-lkhouse-fw — SCD Engine (Slowly Changing Dimensions).
Supports SCD Type 1, 2, 3, 4, and 6 in BigQuery Data Product layer.
Config-driven: specify SCD type and tracking columns in consumption YAML."""
from google.cloud import bigquery
from bt_df_lkhouse_fw.engine.base import log, log_error, LogLevel


class SCDEngine:
    """Implements SCD Types 1, 2, 3, 4, 6 in BigQuery."""

    def __init__(self, project_id: str, dataset: str = "lakehouse_dataproduct"):
        self.project_id = project_id
        self.dataset = dataset
        self.client = bigquery.Client(project=project_id)
        self.full_dataset = f"{project_id}.{dataset}"

    def apply_scd(self, config: dict) -> bool:
        """Apply SCD logic based on config.

        Config format:
        {
            "table": "dim_customer",
            "source_query": "SELECT ... FROM ccn.customers",
            "scd_type": 2,
            "primary_key": "customer_id",
            "tracked_columns": ["name", "email", "region", "loyalty_tier"],
            "metadata_columns": {  # optional overrides
                "effective_from": "effective_from",
                "effective_to": "effective_to",
                "is_current": "is_current",
                "version": "version",
            }
        }
        """
        scd_type = config.get("scd_type", 1)
        table = config["table"]

        log("scd", f"[{table}] Applying SCD Type {scd_type}")

        try:
            if scd_type == 1:
                return self._scd_type1(config)
            elif scd_type == 2:
                return self._scd_type2(config)
            elif scd_type == 3:
                return self._scd_type3(config)
            elif scd_type == 4:
                return self._scd_type4(config)
            elif scd_type == 6:
                return self._scd_type6(config)
            else:
                log_error("scd", f"[{table}] Unsupported SCD type: {scd_type}")
                return False
        except Exception as e:
            log_error("scd", f"[{table}] SCD Type {scd_type} failed", e)
            return False

    def _scd_type1(self, config: dict) -> bool:
        """SCD Type 1: Overwrite. No history kept.
        Simply MERGE source into target, updating changed rows."""
        table = config["table"]
        pk = config["primary_key"]
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        tracked = config.get("tracked_columns", [])
        target = f"`{self.full_dataset}.{table}`"

        # Build update set clause
        update_cols = ", ".join([f"T.{c} = S.{c}" for c in tracked])
        # Build insert columns
        all_cols = [pk] + tracked

        sql = f"""
MERGE {target} T
USING ({source_query}) S
ON T.{pk} = S.{pk}
WHEN MATCHED AND ({' OR '.join([f'T.{c} != S.{c} OR (T.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])})
THEN UPDATE SET {update_cols}, T.updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED
THEN INSERT ({', '.join(all_cols)}, created_at, updated_at)
     VALUES ({', '.join([f'S.{c}' for c in all_cols])}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
"""
        return self._execute(sql, table, "Type 1")

    def _scd_type2(self, config: dict) -> bool:
        """SCD Type 2: Add new row for changes. Full history.
        Columns: effective_from, effective_to, is_current, version."""
        table = config["table"]
        pk = config["primary_key"]
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        tracked = config.get("tracked_columns", [])
        target = f"`{self.full_dataset}.{table}`"

        meta = config.get("metadata_columns", {})
        eff_from = meta.get("effective_from", "effective_from")
        eff_to = meta.get("effective_to", "effective_to")
        is_current = meta.get("is_current", "is_current")
        version = meta.get("version", "version")

        all_cols = [pk] + tracked
        change_condition = ' OR '.join([f'T.{c} != S.{c} OR (T.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])

        # Step 1: Close existing current records that have changes
        close_sql = f"""
UPDATE {target} T
SET T.{eff_to} = CURRENT_TIMESTAMP(), T.{is_current} = FALSE
WHERE T.{is_current} = TRUE
AND T.{pk} IN (
    SELECT S.{pk} FROM ({source_query}) S
    JOIN {target} T2 ON S.{pk} = T2.{pk} AND T2.{is_current} = TRUE
    WHERE {' OR '.join([f'T2.{c} != S.{c} OR (T2.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])}
)
"""

        # Step 2: Insert new versions for changed records + net new records
        insert_sql = f"""
INSERT INTO {target} ({', '.join(all_cols)}, {eff_from}, {eff_to}, {is_current}, {version})
SELECT
    {', '.join([f'S.{c}' for c in all_cols])},
    CURRENT_TIMESTAMP() AS {eff_from},
    CAST('9999-12-31' AS TIMESTAMP) AS {eff_to},
    TRUE AS {is_current},
    COALESCE(T.max_version, 0) + 1 AS {version}
FROM ({source_query}) S
LEFT JOIN (
    SELECT {pk}, MAX({version}) AS max_version
    FROM {target}
    GROUP BY {pk}
) T ON S.{pk} = T.{pk}
WHERE S.{pk} NOT IN (SELECT {pk} FROM {target} WHERE {is_current} = TRUE)
   OR S.{pk} IN (
        SELECT S2.{pk} FROM ({source_query}) S2
        JOIN {target} T3 ON S2.{pk} = T3.{pk} AND T3.{is_current} = TRUE
        WHERE {' OR '.join([f'T3.{c} != S2.{c} OR (T3.{c} IS NULL AND S2.{c} IS NOT NULL)' for c in tracked])}
    )
"""

        # Execute both steps
        success = self._execute(close_sql, table, "Type 2 - close")
        if success:
            success = self._execute(insert_sql, table, "Type 2 - insert")
        return success

    def _scd_type3(self, config: dict) -> bool:
        """SCD Type 3: Previous value columns. Limited history (one prior value).
        Adds prev_{column} for each tracked column."""
        table = config["table"]
        pk = config["primary_key"]
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        tracked = config.get("tracked_columns", [])
        target = f"`{self.full_dataset}.{table}`"

        # Build update: set prev_X = current X, then set X = new value
        update_parts = []
        for c in tracked:
            update_parts.append(f"T.prev_{c} = T.{c}")
            update_parts.append(f"T.{c} = S.{c}")
        update_parts.append("T.updated_at = CURRENT_TIMESTAMP()")
        update_set = ", ".join(update_parts)

        change_condition = ' OR '.join([f'T.{c} != S.{c} OR (T.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])

        all_cols = [pk] + tracked
        prev_cols = [f"prev_{c}" for c in tracked]
        insert_cols = all_cols + prev_cols

        sql = f"""
MERGE {target} T
USING ({source_query}) S
ON T.{pk} = S.{pk}
WHEN MATCHED AND ({change_condition})
THEN UPDATE SET {update_set}
WHEN NOT MATCHED
THEN INSERT ({', '.join(insert_cols)}, created_at, updated_at)
     VALUES ({', '.join([f'S.{c}' for c in all_cols])}, {', '.join(['NULL' for _ in prev_cols])}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
"""
        return self._execute(sql, table, "Type 3")

    def _scd_type4(self, config: dict) -> bool:
        """SCD Type 4: History table. Current in main table, history in separate table.
        Main table: always current. History table: all versions."""
        table = config["table"]
        history_table = config.get("history_table", f"{table}_history")
        pk = config["primary_key"]
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        tracked = config.get("tracked_columns", [])
        target = f"`{self.full_dataset}.{table}`"
        history_target = f"`{self.full_dataset}.{history_table}`"

        all_cols = [pk] + tracked
        change_condition = ' OR '.join([f'T.{c} != S.{c} OR (T.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])

        # Step 1: Insert changed/existing records into history
        history_sql = f"""
INSERT INTO {history_target} ({', '.join(all_cols)}, snapshot_at)
SELECT {', '.join([f'T.{c}' for c in all_cols])}, CURRENT_TIMESTAMP()
FROM {target} T
JOIN ({source_query}) S ON T.{pk} = S.{pk}
WHERE {change_condition}
"""

        # Step 2: Upsert current table (SCD1 style)
        update_cols = ", ".join([f"T.{c} = S.{c}" for c in tracked])
        upsert_sql = f"""
MERGE {target} T
USING ({source_query}) S
ON T.{pk} = S.{pk}
WHEN MATCHED AND ({change_condition})
THEN UPDATE SET {update_cols}, T.updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED
THEN INSERT ({', '.join(all_cols)}, created_at, updated_at)
     VALUES ({', '.join([f'S.{c}' for c in all_cols])}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
"""

        success = self._execute(history_sql, table, "Type 4 - archive")
        if success:
            success = self._execute(upsert_sql, table, "Type 4 - upsert")
        return success

    def _scd_type6(self, config: dict) -> bool:
        """SCD Type 6: Hybrid (1+2+3). Combines:
        - Type 2: new row for history (effective_from/to, is_current)
        - Type 3: prev_ columns on current row
        - Type 1: current_ columns always updated on ALL rows for that key

        Columns: effective_from, effective_to, is_current, version,
                 prev_{col}, current_{col}"""
        table = config["table"]
        pk = config["primary_key"]
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        tracked = config.get("tracked_columns", [])
        target = f"`{self.full_dataset}.{table}`"

        meta = config.get("metadata_columns", {})
        eff_from = meta.get("effective_from", "effective_from")
        eff_to = meta.get("effective_to", "effective_to")
        is_current = meta.get("is_current", "is_current")
        version = meta.get("version", "version")

        change_condition = ' OR '.join([f'T.{c} != S.{c} OR (T.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])

        # Step 1: Update current_ columns on ALL historical rows (Type 1 aspect)
        current_update_parts = ", ".join([f"T.current_{c} = S.{c}" for c in tracked])
        update_current_sql = f"""
UPDATE {target} T
SET {current_update_parts}
FROM ({source_query}) S
WHERE T.{pk} = S.{pk}
"""

        # Step 2: Close current record + set prev_ values (Type 2+3 aspect)
        close_parts = [f"T.{eff_to} = CURRENT_TIMESTAMP()", f"T.{is_current} = FALSE"]
        for c in tracked:
            close_parts.append(f"T.prev_{c} = T.{c}")
        close_set = ", ".join(close_parts)

        close_sql = f"""
UPDATE {target} T
SET {close_set}
WHERE T.{is_current} = TRUE
AND T.{pk} IN (
    SELECT S.{pk} FROM ({source_query}) S
    JOIN {target} T2 ON S.{pk} = T2.{pk} AND T2.{is_current} = TRUE
    WHERE {' OR '.join([f'T2.{c} != S.{c} OR (T2.{c} IS NULL AND S.{c} IS NOT NULL)' for c in tracked])}
)
"""

        # Step 3: Insert new version (Type 2 aspect)
        all_cols = [pk] + tracked
        current_cols = [f"current_{c}" for c in tracked]
        prev_cols = [f"prev_{c}" for c in tracked]

        insert_sql = f"""
INSERT INTO {target} ({', '.join(all_cols)}, {', '.join(current_cols)}, {', '.join(prev_cols)}, {eff_from}, {eff_to}, {is_current}, {version})
SELECT
    {', '.join([f'S.{c}' for c in all_cols])},
    {', '.join([f'S.{c}' for c in tracked])},
    {', '.join([f'T.{c}' for c in tracked])},
    CURRENT_TIMESTAMP(),
    CAST('9999-12-31' AS TIMESTAMP),
    TRUE,
    COALESCE(T.max_ver, 0) + 1
FROM ({source_query}) S
LEFT JOIN (
    SELECT {pk}, MAX({version}) AS max_ver, {', '.join(tracked)}
    FROM {target}
    WHERE {is_current} = TRUE
    GROUP BY {pk}, {', '.join(tracked)}
) T ON S.{pk} = T.{pk}
WHERE S.{pk} NOT IN (SELECT {pk} FROM {target} WHERE {is_current} = TRUE)
   OR S.{pk} IN (
        SELECT S2.{pk} FROM ({source_query}) S2
        JOIN {target} T3 ON S2.{pk} = T3.{pk} AND T3.{is_current} = TRUE
        WHERE {' OR '.join([f'T3.{c} != S2.{c} OR (T3.{c} IS NULL AND S2.{c} IS NOT NULL)' for c in tracked])}
    )
"""

        success = self._execute(update_current_sql, table, "Type 6 - update current_")
        if success:
            success = self._execute(close_sql, table, "Type 6 - close")
        if success:
            success = self._execute(insert_sql, table, "Type 6 - insert")
        return success

    def ensure_table_schema(self, config: dict) -> bool:
        """Create target table with correct schema if it doesn't exist."""
        table = config["table"]
        pk = config["primary_key"]
        scd_type = config.get("scd_type", 1)
        tracked = config.get("tracked_columns", [])
        source_query = config["source_query"].replace("${PROJECT_ID}", self.project_id)
        target = f"`{self.full_dataset}.{table}`"

        # Check if table exists
        try:
            self.client.get_table(f"{self.full_dataset}.{table}")
            log("scd", f"[{table}] Table exists")
            return True
        except Exception:
            pass

        # Build CREATE TABLE based on SCD type
        log("scd", f"[{table}] Creating table with SCD Type {scd_type} schema")

        if scd_type == 1:
            sql = f"""
CREATE TABLE {target} AS
SELECT *, CURRENT_TIMESTAMP() AS created_at, CURRENT_TIMESTAMP() AS updated_at
FROM ({source_query}) LIMIT 0
"""
        elif scd_type == 2:
            meta = config.get("metadata_columns", {})
            sql = f"""
CREATE TABLE {target} AS
SELECT *,
    CURRENT_TIMESTAMP() AS {meta.get('effective_from', 'effective_from')},
    CAST('9999-12-31' AS TIMESTAMP) AS {meta.get('effective_to', 'effective_to')},
    TRUE AS {meta.get('is_current', 'is_current')},
    1 AS {meta.get('version', 'version')}
FROM ({source_query}) LIMIT 0
"""
        elif scd_type == 3:
            prev_cols = ", ".join([f"CAST(NULL AS STRING) AS prev_{c}" for c in tracked])
            sql = f"""
CREATE TABLE {target} AS
SELECT *, {prev_cols},
    CURRENT_TIMESTAMP() AS created_at, CURRENT_TIMESTAMP() AS updated_at
FROM ({source_query}) LIMIT 0
"""
        elif scd_type == 4:
            sql = f"""
CREATE TABLE {target} AS
SELECT *, CURRENT_TIMESTAMP() AS created_at, CURRENT_TIMESTAMP() AS updated_at
FROM ({source_query}) LIMIT 0
"""
            # Also create history table
            history_table = config.get("history_table", f"{table}_history")
            history_target = f"`{self.full_dataset}.{history_table}`"
            history_sql = f"""
CREATE TABLE IF NOT EXISTS {history_target} AS
SELECT *, CURRENT_TIMESTAMP() AS snapshot_at
FROM ({source_query}) LIMIT 0
"""
            self._execute(history_sql, history_table, "create history table")

        elif scd_type == 6:
            meta = config.get("metadata_columns", {})
            current_cols = ", ".join([f"CAST(NULL AS STRING) AS current_{c}" for c in tracked])
            prev_cols = ", ".join([f"CAST(NULL AS STRING) AS prev_{c}" for c in tracked])
            sql = f"""
CREATE TABLE {target} AS
SELECT *, {current_cols}, {prev_cols},
    CURRENT_TIMESTAMP() AS {meta.get('effective_from', 'effective_from')},
    CAST('9999-12-31' AS TIMESTAMP) AS {meta.get('effective_to', 'effective_to')},
    TRUE AS {meta.get('is_current', 'is_current')},
    1 AS {meta.get('version', 'version')}
FROM ({source_query}) LIMIT 0
"""
        else:
            return False

        return self._execute(sql, table, f"create SCD{scd_type} table")

    def _execute(self, sql: str, table: str, step: str) -> bool:
        """Execute SQL in BigQuery."""
        try:
            job = self.client.query(sql)
            job.result()
            log("scd", f"[{table}] {step} - OK")
            return True
        except Exception as e:
            log_error("scd", f"[{table}] {step} - FAILED", e)
            return False
