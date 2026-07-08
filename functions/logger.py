"""Centralized Structured Logger — Writes JSON logs to GCS bucket.

All modules import and use this logger. Logs are accumulated in memory
and flushed to GCS as a JSONL file (one JSON object per line).

JSONL format is ideal for:
- BigQuery (load directly as external table or native table)
- Cloud Logging / Log Analytics
- Pandas / Spark analysis
- Grep / jq command-line analysis

Usage:
    from logger import get_logger
    log = get_logger("discovery.suggester")
    log.info("Discovery started", asset_name="cibil_feed", fields=12)
    log.error("LLM call failed", error=str(e), model="gpt-4")

    # At end of request/pipeline:
    from logger import flush_logs
    flush_logs()
"""
import os
import json
import time
import threading
import traceback
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent / "discovery" / ".env")
except ImportError:
    pass

_LOG_BUCKET = os.environ.get("LOG_BUCKET", os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"))
_LOG_PREFIX = os.environ.get("LOG_PREFIX", "logs/app")
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}
_lock = threading.Lock()
_buffer: list[dict] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _should_log(level: str) -> bool:
    return _LEVEL_ORDER.get(level, 1) >= _LEVEL_ORDER.get(_LOG_LEVEL, 1)


class Logger:
    """Structured logger that accumulates JSON log entries."""

    def __init__(self, module: str):
        self.module = module

    def _emit(self, level: str, message: str, **kwargs):
        if not _should_log(level):
            return
        entry = {
            "timestamp": _now_iso(),
            "level": level,
            "module": self.module,
            "message": message,
        }
        if kwargs:
            entry["metadata"] = kwargs
        with _lock:
            _buffer.append(entry)

    def debug(self, message: str, **kwargs):
        self._emit("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._emit("INFO", message, **kwargs)

    def warn(self, message: str, **kwargs):
        self._emit("WARN", message, **kwargs)

    def error(self, message: str, **kwargs):
        if "traceback" not in kwargs:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                kwargs["traceback"] = tb
        self._emit("ERROR", message, **kwargs)

    def fatal(self, message: str, **kwargs):
        self._emit("FATAL", message, **kwargs)


_loggers: dict[str, Logger] = {}


def get_logger(module: str) -> Logger:
    """Get or create a logger for the given module name."""
    if module not in _loggers:
        _loggers[module] = Logger(module)
    return _loggers[module]


def get_log_buffer() -> list[dict]:
    """Return current log buffer (for inspection/testing)."""
    with _lock:
        return list(_buffer)


def flush_logs(stage: Optional[str] = None) -> Optional[str]:
    """Flush accumulated logs to GCS as a JSONL file. Returns the GCS path or None.

    Args:
        stage: Optional label (e.g. 'discovery', 'ingest') used in the blob path.
    """
    with _lock:
        if not _buffer:
            return None
        entries = list(_buffer)
        _buffer.clear()

    stage = stage or "app"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    blob_path = f"{_LOG_PREFIX}/{stage}/{run_id}.jsonl"
    content = "\n".join(json.dumps(e, default=str) for e in entries)

    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(_LOG_BUCKET)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="application/x-ndjson")
        return f"gs://{_LOG_BUCKET}/{blob_path}"
    except Exception as e:
        # Fallback: print to stdout so logs aren't lost
        print(f"[logger] GCS flush failed ({e}), dumping {len(entries)} entries to stdout")
        for entry in entries:
            print(json.dumps(entry, default=str))
        return None
