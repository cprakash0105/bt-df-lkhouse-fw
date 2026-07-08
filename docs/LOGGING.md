# Structured Logging

All application-level logs are written as **JSONL** (newline-delimited JSON) to a GCS bucket. This makes them queryable via BigQuery, loadable into Pandas/Spark, and greppable with `jq`.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Application Code                                             │
│  (Discovery API, LLM Client, Suggester, Pipeline Functions)   │
│                                                               │
│  from logger import get_logger, flush_logs                    │
│  _log = get_logger("module.name")                            │
│  _log.info("message", key="value")                           │
└──────────────────────┬───────────────────────────────────────┘
                       │ flush_logs("stage")
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  GCS: gs://{BUCKET}/logs/app/{stage}/{timestamp}.jsonl        │
└──────────────────────┬───────────────────────────────────────┘
                       │ BigQuery external table
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  BigQuery: lakehouse_logs.app_logs                            │
│  SELECT * WHERE level = 'ERROR' AND module = 'discovery.api'  │
└──────────────────────────────────────────────────────────────┘
```

## Log Entry Format

Each line in a JSONL file is a self-contained JSON object:

```json
{
  "timestamp": "2025-01-15T10:30:45.123Z",
  "level": "INFO",
  "module": "discovery.llm_client",
  "message": "LLM call succeeded",
  "metadata": {
    "model": "openai.gpt-oss-120b",
    "duration_ms": 1234,
    "prompt_tokens": 500,
    "completion_tokens": 120,
    "user_prompt_preview": "Extract dataset fields..."
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601) | UTC timestamp with millisecond precision |
| `level` | string | `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` |
| `module` | string | Dot-separated module path (e.g. `discovery.api`) |
| `message` | string | Human-readable log message |
| `metadata` | object (optional) | Structured key-value pairs for filtering/analysis |

## GCS Path Convention

```
gs://{BUCKET}/logs/app/{stage}/{YYYYMMDD_HHMMSS_mmm}.jsonl
```

- **stage** — logical grouping: `discovery`, `approval`, `pipeline`, `app`
- **timestamp** — UTC, ensures uniqueness and natural ordering

## Configuration

Set via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_BUCKET` | Value of `CONFIG_BUCKET` or `bt-df-lkhouse-lakehouse` | GCS bucket for logs |
| `LOG_PREFIX` | `logs/app` | Path prefix within the bucket |
| `LOG_LEVEL` | `INFO` | Minimum level to capture (`DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL`) |

## Usage

### Basic usage in any module

```python
from logger import get_logger, flush_logs

_log = get_logger("my.module")

_log.info("Processing started", asset_name="cibil_feed", fields=12)
_log.warn("Fallback used", reason="LLM timeout")
_log.error("Operation failed", error=str(e), table="customers")

# Flush to GCS at end of request/pipeline
flush_logs("my_stage")
```

### Flush via API

```bash
curl -X POST http://localhost:8000/logs/flush
# Returns: {"status": "flushed", "gcs_path": "gs://bucket/logs/app/discovery/20250115_103045_123.jsonl"}
```

## Modules with Logging

| Module | What's logged |
|--------|---------------|
| `discovery.api` | All API requests (discover, approve, ask), errors |
| `discovery.llm_client` | Every LLM call: model, latency, token usage, errors |
| `discovery.suggester` | Discovery start/complete, field match stats |
| `discovery.approval_handler` | Approval actions, terms created, configs pushed |
| `discovery.rag.embedder` | Embedding calls, fallback usage |
| `functions.pipeline_trigger` | Pipeline trigger events, completion/failure |

The Spark pipeline engines (`bt_df_lkhouse_fw`, `eastside`) have their own logging in `base.py` that writes to `gs://{BUCKET}/logs/{stage}/{run_id}.jsonl` — same JSONL format, compatible with the same BigQuery table.

## BigQuery Setup

Run once to create the external table:

```bash
# Replace ${PROJECT_ID} and ${BUCKET} with actual values
sed -e 's/${PROJECT_ID}/bt-df-lkhouse/g' -e 's/${BUCKET}/bt-df-lkhouse-lakehouse/g' \
  scripts/setup_log_table.sql | bq query --use_legacy_sql=false
```

Or manually in the BigQuery console — see `scripts/setup_log_table.sql`.

## Analysis Examples

### Errors in the last 24 hours

```sql
SELECT timestamp, module, message, JSON_VALUE(metadata, '$.error') as error
FROM `bt-df-lkhouse.lakehouse_logs.app_logs`
WHERE level = 'ERROR'
  AND timestamp > FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR))
ORDER BY timestamp DESC
```

### LLM latency percentiles

```sql
SELECT
  JSON_VALUE(metadata, '$.model') as model,
  COUNT(*) as calls,
  APPROX_QUANTILES(CAST(JSON_VALUE(metadata, '$.duration_ms') AS INT64), 100)[OFFSET(50)] as p50_ms,
  APPROX_QUANTILES(CAST(JSON_VALUE(metadata, '$.duration_ms') AS INT64), 100)[OFFSET(95)] as p95_ms,
  SUM(CAST(JSON_VALUE(metadata, '$.prompt_tokens') AS INT64)) as total_prompt_tokens
FROM `bt-df-lkhouse.lakehouse_logs.app_logs`
WHERE module = 'discovery.llm_client'
  AND message = 'LLM call succeeded'
GROUP BY model
```

### Discovery activity by dataset

```sql
SELECT
  JSON_VALUE(metadata, '$.asset_name') as dataset,
  COUNT(*) as discoveries,
  MAX(timestamp) as last_discovered
FROM `bt-df-lkhouse.lakehouse_logs.app_logs`
WHERE module = 'discovery.suggester'
  AND message = 'Full discovery complete'
GROUP BY dataset
ORDER BY discoveries DESC
```

### Pipeline failures

```sql
SELECT timestamp, JSON_VALUE(metadata, '$.table_name') as table_name,
       JSON_VALUE(metadata, '$.error') as error
FROM `bt-df-lkhouse.lakehouse_logs.app_logs`
WHERE module = 'functions.pipeline_trigger' AND level = 'ERROR'
ORDER BY timestamp DESC
```

### Load into Pandas (local analysis)

```python
import pandas as pd
from google.cloud import storage
import json

client = storage.Client()
bucket = client.bucket("bt-df-lkhouse-lakehouse")
blobs = bucket.list_blobs(prefix="logs/app/discovery/")

records = []
for blob in blobs:
    for line in blob.download_as_text().strip().split("\n"):
        records.append(json.loads(line))

df = pd.json_normalize(records)
df["timestamp"] = pd.to_datetime(df["timestamp"])
```

## Fallback Behaviour

If GCS is unavailable (e.g. local development, missing credentials), `flush_logs()` prints all buffered entries to stdout as JSON. Logs are never silently lost.
