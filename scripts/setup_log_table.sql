-- Create BigQuery external table over GCS JSONL logs.
-- Run once to set up, then query logs with standard SQL.
--
-- Usage:
--   bq query --use_legacy_sql=false < scripts/setup_log_table.sql
--
-- After setup, query examples:
--   SELECT * FROM `${PROJECT_ID}.lakehouse_logs.app_logs` WHERE level = 'ERROR' ORDER BY timestamp DESC LIMIT 50;
--   SELECT module, COUNT(*) as cnt FROM `${PROJECT_ID}.lakehouse_logs.app_logs` GROUP BY module ORDER BY cnt DESC;
--   SELECT * FROM `${PROJECT_ID}.lakehouse_logs.app_logs` WHERE JSON_VALUE(metadata, '$.asset_name') = 'cibil_feed';
--   SELECT JSON_VALUE(metadata, '$.model') as model, AVG(CAST(JSON_VALUE(metadata, '$.duration_ms') AS INT64)) as avg_ms
--     FROM `${PROJECT_ID}.lakehouse_logs.app_logs` WHERE module = 'discovery.llm_client' GROUP BY model;

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.lakehouse_logs`
OPTIONS (location = 'europe-west2');

CREATE OR REPLACE EXTERNAL TABLE `${PROJECT_ID}.lakehouse_logs.app_logs` (
  timestamp STRING,
  level STRING,
  module STRING,
  message STRING,
  metadata JSON
)
OPTIONS (
  format = 'JSON',
  uris = ['gs://${BUCKET}/logs/app/*/*.jsonl']
);
