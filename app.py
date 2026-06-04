"""
app.py  —  Flask REST API  (Phase 5)
=====================================
Converts the command-line monitoring script into a persistent monitoring
SERVICE with HTTP endpoints that any client (browser, dashboard, CI/CD
pipeline, alerting tool) can query.

Architecture:
    • A background daemon thread runs health checks every MONITOR_INTERVAL
      seconds and writes results into thread-safe shared state.
    • Flask endpoints READ from that shared state and return JSON responses.
    • The monitoring loop and the HTTP server run concurrently in the same
      process using Python's threading module.

Industry context:
    This pattern (background worker + HTTP API) is used in:
        • Prometheus exporters  (expose metrics over HTTP for Grafana)
        • Kubernetes operators  (watch cluster state, expose health endpoints)
        • Sidecar containers    (health and metrics proxies in service meshes)

API Endpoints:
    GET  /health          Service liveness check (used by load balancers / k8s)
    GET  /websites        Latest results for all monitored URLs
    GET  /websites/<url>  Single website result
    GET  /metrics         Aggregate statistics (availability %, avg response)
    GET  /logs            Recent log entries
    POST /check           Trigger an immediate on-demand health check

Run locally:
    python app.py

Run with Docker (Phase 6):
    docker build -t health-monitor .
    docker run -p 5000:5000 health-monitor
"""

import os
import time
import threading
from datetime import datetime

from flask import Flask, jsonify, request

from monitor import (
    load_websites,
    check_websites_concurrent,
    compute_summary,
    STATUS_UP,
)
from logger import write_logs_batch, read_logs, get_log_stats


# ─────────────────────────────────────────────────────────────────────────────
# FLASK APP INITIALISATION
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

# Disable key sorting in JSON responses — preserve our dict key order
app.json.sort_keys = False


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# Using os.environ.get() means configuration can be injected at runtime:
#   - locally:  export MONITOR_INTERVAL=30 && python app.py
#   - Docker:   docker run -e MONITOR_INTERVAL=30 ...
#   - k8s:      set via ConfigMap or Deployment env block
# This is the Twelve-Factor App methodology (config in environment).
# ─────────────────────────────────────────────────────────────────────────────

MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL", "60"))   # seconds
WEBSITES_FILE    = os.environ.get("WEBSITES_FILE",    "websites.txt")
FLASK_PORT       = int(os.environ.get("PORT",         "5000"))
FLASK_DEBUG      = os.environ.get("FLASK_DEBUG",      "false").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────────
# SHARED STATE  (thread-safe)
#
# The monitoring thread WRITES here; the Flask routes READ from here.
# threading.Lock() ensures only one thread accesses the state at a time,
# preventing race conditions (corrupted data from concurrent reads/writes).
# ─────────────────────────────────────────────────────────────────────────────

_lock            = threading.Lock()
_latest_results: list  = []        # Most recent check results
_last_check_at:  str | None = None # ISO timestamp of last check
_check_count:    int   = 0         # Total number of checks completed


def _read_state() -> tuple:
    """Thread-safe snapshot of shared monitoring state."""
    with _lock:
        return list(_latest_results), _last_check_at, _check_count


def _write_state(results: list, timestamp: str) -> None:
    """Thread-safe update to shared monitoring state."""
    global _latest_results, _last_check_at, _check_count
    with _lock:
        _latest_results = results
        _last_check_at  = timestamp
        _check_count   += 1


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND MONITORING LOOP
# ─────────────────────────────────────────────────────────────────────────────

def _monitoring_loop() -> None:
    """
    Runs forever in a background daemon thread.

    daemon=True means this thread is killed automatically when the main
    process exits — no need to explicitly stop it.

    Loop behaviour:
        1. Load URLs from websites.txt
        2. Run concurrent health checks
        3. Update shared state (thread-safe)
        4. Write results to logs.txt
        5. Sleep for MONITOR_INTERVAL seconds
        6. Repeat
    """
    while True:
        try:
            urls = load_websites(WEBSITES_FILE)

            if urls:
                results   = check_websites_concurrent(urls)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                _write_state(results, timestamp)
                write_logs_batch(results)

                up_count = sum(1 for r in results if r["status"] == STATUS_UP)
                print(
                    f"[{timestamp}] Check #{_check_count} complete — "
                    f"{up_count}/{len(results)} UP"
                )
            else:
                print(f"[WARN] No URLs in '{WEBSITES_FILE}'. "
                      f"Retrying in {MONITOR_INTERVAL}s...")

        except Exception as exc:
            print(f"[ERROR] Monitoring loop crashed: {exc}")

        time.sleep(MONITOR_INTERVAL)


def _start_background_monitor() -> None:
    """Launch the monitoring loop as a background daemon thread."""
    thread = threading.Thread(
        target=_monitoring_loop,
        daemon=True,
        name="monitor-loop",
    )
    thread.start()
    print(f"[INFO] Background monitor started (interval: {MONITOR_INTERVAL}s)")


# ─────────────────────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """
    GET /health
    ───────────
    Returns the operational status of this monitoring SERVICE (not of the
    monitored websites — that's /websites).

    Used by:
        • Load balancers (AWS ALB, nginx) to decide whether to route traffic
        • Kubernetes liveness probes  (kill and restart if unhealthy)
        • Docker HEALTHCHECK          (mark container healthy/unhealthy)
        • Uptime monitors watching the monitor itself

    HTTP 200  always — if you get a response, the service is alive.
    """
    _, last_check, count = _read_state()

    return jsonify({
        "status":                    "healthy",
        "service":                   "website-health-monitor",
        "version":                   "1.0.0",
        "timestamp":                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_check_at":             last_check,
        "total_checks_completed":    count,
        "websites_configured":       len(load_websites(WEBSITES_FILE)),
        "monitor_interval_seconds":  MONITOR_INTERVAL,
    }), 200


@app.route("/websites", methods=["GET"])
def websites():
    """
    GET /websites
    ─────────────
    Returns the latest health check result for every monitored URL.

    Optional query parameters:
        ?status=UP    → only UP sites
        ?status=DOWN  → only DOWN sites

    Example response:
        {
          "last_check_at": "2026-06-01 10:15:32",
          "count": 5,
          "websites": [
            {
              "url": "https://google.com",
              "status": "UP",
              "status_code": 200,
              "response_time_ms": 98,
              "performance": "Excellent",
              "error": null,
              "timestamp": "2026-06-01 10:15:32"
            }, ...
          ]
        }
    """
    results, last_check, _ = _read_state()

    status_filter = request.args.get("status", "").upper()
    if status_filter in ("UP", "DOWN"):
        results = [r for r in results if r["status"] == status_filter]

    return jsonify({
        "last_check_at": last_check,
        "count":         len(results),
        "websites":      results,
    }), 200


@app.route("/websites/<path:encoded_url>", methods=["GET"])
def website_detail(encoded_url: str):
    """
    GET /websites/<url>
    ───────────────────
    Returns the latest result for a single website.

    Usage:
        GET /websites/google.com
        GET /websites/github.com
    """
    results, _, _ = _read_state()

    # Match regardless of http/https prefix in the stored result
    match = next(
        (
            r for r in results
            if r["url"].replace("https://", "").replace("http://", "")
               == encoded_url
        ),
        None,
    )

    if match:
        return jsonify(match), 200

    return jsonify({
        "error": f"No result found for: {encoded_url}",
        "hint":  "Omit https:// in the URL path. e.g. /websites/google.com",
    }), 404


@app.route("/metrics", methods=["GET"])
def metrics():
    """
    GET /metrics
    ────────────
    Returns aggregate statistics across all monitored websites.
    This is the "dashboard summary" endpoint — used by:
        • Grafana dashboards (via JSON API data source)
        • Alerting rules     (if availability_pct < 90, fire alert)
        • CI/CD pipelines    (block deployment if critical sites are DOWN)
        • Status page generators

    Example response:
        {
          "total": 10,
          "up": 9,
          "down": 1,
          "availability_pct": 90.0,
          "avg_response_ms": 145,
          "min_response_ms": 88,
          "max_response_ms": 850,
          "slow_count": 1,
          "performance_tiers": { "excellent": 4, "good": 3, ... },
          "last_check_at": "2026-06-01 10:15:32",
          "checks_run": 42
        }
    """
    results, last_check, count = _read_state()

    summary = compute_summary(results)
    summary["last_check_at"] = last_check
    summary["checks_run"]    = count

    return jsonify(summary), 200


@app.route("/logs", methods=["GET"])
def logs():
    """
    GET /logs
    ─────────
    Returns recent log entries from logs.txt.

    Query parameters:
        ?limit=N  → return last N entries (default: 50, max: 500)

    In production you'd query Elasticsearch / Loki / Splunk here instead
    of reading a flat file, but the API contract stays the same.
    """
    limit   = min(request.args.get("limit", 50, type=int), 500)
    entries = read_logs(limit)
    stats   = get_log_stats()

    return jsonify({
        "log_file":          stats.get("log_file"),
        "log_file_size_kb":  stats.get("log_file_size_kb"),
        "total_entries":     stats.get("total_log_entries"),
        "returned":          len(entries),
        "logs":              entries,
    }), 200


@app.route("/check", methods=["POST"])
def trigger_check():
    """
    POST /check
    ───────────
    Trigger an immediate health check on demand — without waiting for
    the next scheduled interval.

    Use cases:
        • After a deployment: verify all sites are still UP
        • During an incident: get fresh data immediately
        • In CI/CD pipelines: automated smoke testing after deploy

    Returns the same payload as /metrics plus the full website results.
    """
    urls = load_websites(WEBSITES_FILE)
    if not urls:
        return jsonify({
            "error": "No websites configured.",
            "hint":  f"Add URLs to '{WEBSITES_FILE}', one per line.",
        }), 400

    results   = check_websites_concurrent(urls)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _write_state(results, timestamp)
    write_logs_batch(results)

    summary             = compute_summary(results)
    summary["triggered_at"] = timestamp
    summary["websites"] = results

    return jsonify(summary), 200


# ─────────────────────────────────────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_err):
    return jsonify({
        "error":               "Endpoint not found",
        "available_endpoints": [
            "GET  /health",
            "GET  /websites",
            "GET  /websites/<url>",
            "GET  /metrics",
            "GET  /logs?limit=N",
            "POST /check",
        ],
    }), 404


@app.errorhandler(405)
def method_not_allowed(_err):
    return jsonify({"error": "HTTP method not allowed on this endpoint"}), 405


@app.errorhandler(500)
def internal_error(err):
    return jsonify({"error": "Internal server error", "message": str(err)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  Website Health Monitoring System  —  REST API")
    print("=" * 62)
    print(f"  Monitor interval : every {MONITOR_INTERVAL} seconds")
    print(f"  Websites file    : {WEBSITES_FILE}")
    print(f"  API base URL     : http://0.0.0.0:{FLASK_PORT}")
    print(f"  Debug mode       : {FLASK_DEBUG}")
    print("=" * 62)
    print("\n  Endpoints:")
    print("    GET  http://localhost:5000/health")
    print("    GET  http://localhost:5000/websites")
    print("    GET  http://localhost:5000/metrics")
    print("    GET  http://localhost:5000/logs")
    print("    POST http://localhost:5000/check")
    print("=" * 62 + "\n")

    # Run first check synchronously before starting background thread
    # so the API has data to return immediately on first request
    urls = load_websites(WEBSITES_FILE)
    if urls:
        print("[INFO] Running initial health check before starting API...")
        initial_results = check_websites_concurrent(urls)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_state(initial_results, ts)
        write_logs_batch(initial_results)
        print(f"[INFO] Initial check complete — {len(initial_results)} sites checked.\n")

    # Start the background monitoring loop
    _start_background_monitor()

    # Start Flask (blocking — runs until Ctrl+C or container stop)
    app.run(
        host="0.0.0.0",         # Listen on all interfaces (required for Docker)
        port=FLASK_PORT,
        debug=FLASK_DEBUG,
        use_reloader=False,     # Disable reloader — it would start a second
                                # monitoring thread in debug mode
    )
