"""
logger.py  —  Structured Logging & Monitoring History  (Phase 3)
=================================================================
Provides two capabilities:

  1. WRITING LOGS  — append each health check result to logs.txt in a
     structured, human-readable format.  Built on Python's standard
     'logging' module (the same module used in enterprise production code).

  2. READING LOGS  — query the log file to retrieve history and
     compute aggregate statistics without a database.

Industry context:
    In production systems, logs flow from applications into centralised
    log aggregation platforms such as:
        • ELK Stack  (Elasticsearch + Logstash + Kibana)
        • Grafana Loki
        • Splunk
        • AWS CloudWatch Logs
        • Google Cloud Logging

    This module produces the raw log entries.  The centralised platform
    would ingest, index, and visualise them.  Understanding this pipeline
    is essential for DevOps/SRE roles.

Log format:
    2026-06-01 10:15:32 | https://google.com | UP | 200 | 110 ms | Excellent
    2026-06-01 10:15:33 | https://badsite.com | DOWN | Connection Failed
"""

import logging
import os
from datetime import datetime


# ── Configuration ─────────────────────────────────────────────────────────────

LOG_FILE    = "logs.txt"          # Output file (append mode — never overwrite)
LOG_FORMAT  = "%(asctime)s | %(message)s"   # Each line: timestamp | message
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"           # ISO-style date for easy parsing

# Module-level logger singleton — initialised once, reused on every call.
# Using a module-level variable prevents creating duplicate handlers on
# repeated calls to _get_logger(), which would cause duplicate log entries.
_logger: logging.Logger | None = None


# ── Internal logger factory ────────────────────────────────────────────────────

def _get_logger() -> logging.Logger:
    """
    Return the configured logger, initialising it on first call.

    Uses Python's logging module — the standard for structured logging in Python.
    It handles:
        • Thread safety  (safe to call from multiple threads simultaneously)
        • Buffering      (efficient file I/O)
        • Handler deduplication (won't add handlers twice)
    """
    global _logger

    if _logger is not None:
        return _logger

    _logger = logging.getLogger("website_monitor")
    _logger.setLevel(logging.INFO)

    # Guard: only add handlers if none exist yet
    # (prevents duplicate entries if module is reloaded in tests)
    if not _logger.handlers:
        # ── File handler: append every entry to logs.txt ──────────────────
        # mode='a' = APPEND (never truncate existing history)
        # encoding='utf-8' = handle international domain names safely
        file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        )
        _logger.addHandler(file_handler)

    # Prevent log records from also propagating to the root logger
    # (avoids duplicate output in Flask's log stream)
    _logger.propagate = False

    return _logger


# ── Public API ─────────────────────────────────────────────────────────────────

def write_log(result: dict) -> None:
    """
    Append a single health check result to logs.txt.

    Called after every check — from run_health_check() (Phase 3) and
    from the Flask background thread (Phase 5).

    Log line examples:
        UP site  : "2026-06-01 10:15:32 | https://google.com | UP | 200 | 98 ms | Excellent"
        DOWN site: "2026-06-01 10:15:33 | https://badsite.com | DOWN | Connection Failed (DNS / network)"
    """
    logger = _get_logger()

    url    = result.get("url",    "unknown")
    status = result.get("status", "UNKNOWN")

    if status == "UP":
        code  = result.get("status_code",      "N/A")
        ms    = result.get("response_time_ms", "N/A")
        perf  = result.get("performance",      "")
        message = f"{url} | {status} | {code} | {ms} ms | {perf}"
    else:
        error   = result.get("error", "Unknown error")
        message = f"{url} | {status} | {error}"

    logger.info(message)


def write_logs_batch(results: list) -> None:
    """
    Write a complete set of check results to logs.txt in one pass.
    Called at the end of each monitoring cycle.
    """
    for result in results:
        write_log(result)


def read_logs(limit: int = 100) -> list:
    """
    Return the last `limit` log entries as a list of strings.

    Most recent entries are LAST in the returned list (chronological order),
    which matches how tail(1) works and how log viewers display history.

    Returns:
        list of log-line strings (empty list if file doesn't exist yet)
    """
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = [line.strip() for line in lines if line.strip()]
        return entries[-limit:]          # Last N entries
    except FileNotFoundError:
        return []                        # No logs yet — not an error
    except Exception as exc:
        return [f"[ERROR] Could not read log file: {str(exc)}"]


def get_log_stats() -> dict:
    """
    Parse the full log file and return aggregate statistics.

    Useful for the /logs API endpoint and for trend analysis without
    setting up a database.  In production you'd query Elasticsearch
    or a time-series DB for this, but file-based stats work well for
    small-to-medium deployments.

    Returns:
        dict with counts, file path, and basic UP/DOWN breakdown
    """
    all_logs = read_logs(limit=100_000)   # Read everything for stats
    total    = len(all_logs)
    up_count = sum(1 for line in all_logs if " | UP | "   in line)
    dn_count = sum(1 for line in all_logs if " | DOWN | " in line)

    return {
        "total_log_entries": total,
        "up_count":          up_count,
        "down_count":        dn_count,
        "log_file":          os.path.abspath(LOG_FILE),
        "log_file_size_kb":  _file_size_kb(LOG_FILE),
    }


def clear_logs() -> bool:
    """
    Erase the log file (use with caution).
    Useful during development or testing.
    Returns True on success, False on failure.
    """
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("")
        return True
    except Exception:
        return False


# ── Internal helper ────────────────────────────────────────────────────────────

def _file_size_kb(filepath: str) -> float:
    """Return file size in kilobytes, or 0 if the file doesn't exist."""
    try:
        return round(os.path.getsize(filepath) / 1024, 2)
    except FileNotFoundError:
        return 0.0
