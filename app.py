"""
app.py  —  Flask REST API  (Phase 5 + Phase 7 DB integration)
==============================================================
Phase 5 : REST API  — /health, /websites, /metrics, /logs, /check
Phase 7 : Database  — 5 new analytics endpoints powered by MySQL

New endpoints added in Phase 7:
    GET /analytics          — combined analytics (uptime + response + failures)
    GET /analytics/uptime   — uptime percentage per website
    GET /analytics/failures — downtime incidents and most failing websites
    GET /history            — full check history from MySQL
    GET /db/status          — database connection status and statistics

What changed from Phase 5:
    - Imported database module
    - Background monitoring loop now also writes results to MySQL
    - 5 new routes added at the bottom
    - All existing routes and behaviour unchanged
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

# ── Phase 7: Import database module ──────────────────────────────────────────
try:
    import database as db
    _DB_MODULE_LOADED = True
except Exception as _db_err:
    _DB_MODULE_LOADED = False
    print(f"[WARN] database.py could not be loaded: {_db_err}")


# ─────────────────────────────────────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.json.sort_keys = False


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

MONITOR_INTERVAL = int(os.environ.get("MONITOR_INTERVAL", "60"))
WEBSITES_FILE    = os.environ.get("WEBSITES_FILE",    "websites.txt")
FLASK_PORT       = int(os.environ.get("PORT",         "5000"))
FLASK_DEBUG      = os.environ.get("FLASK_DEBUG",      "false").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────────
# SHARED STATE (thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

_lock            = threading.Lock()
_latest_results: list      = []
_last_check_at:  str | None = None
_check_count:    int        = 0


def _read_state() -> tuple:
    with _lock:
        return list(_latest_results), _last_check_at, _check_count


def _write_state(results: list, timestamp: str) -> None:
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
    Every MONITOR_INTERVAL seconds:
        1. Check all websites concurrently
        2. Update shared in-memory state
        3. Write to logs.txt (existing Phase 3 behaviour)
        4. Write to MySQL   (new Phase 7 behaviour)
    """
    while True:
        try:
            urls = load_websites(WEBSITES_FILE)

            if urls:
                results   = check_websites_concurrent(urls)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Update shared state (Flask routes read from here)
                _write_state(results, timestamp)

                # Write to logs.txt
                write_logs_batch(results)

                # ── Phase 7: Write to MySQL ───────────────────────────────────
                if _DB_MODULE_LOADED and db.DB_ENABLED:
                    try:
                        saved = db.log_health_checks_batch(results)
                        print(
                            f"[{timestamp}] Check #{_check_count} complete — "
                            f"{sum(1 for r in results if r['status'] == STATUS_UP)}"
                            f"/{len(results)} UP  |  DB: {saved} rows saved"
                        )
                    except Exception as exc:
                        print(f"[DB] Warning: {exc}")
                else:
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
    thread = threading.Thread(
        target=_monitoring_loop,
        daemon=True,
        name="monitor-loop",
    )
    thread.start()
    print(f"[INFO] Background monitor started (interval: {MONITOR_INTERVAL}s)")


# ─────────────────────────────────────────────────────────────────────────────
# ── EXISTING PHASE 5 ROUTES (unchanged) ──────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """
    GET /health
    Service liveness check — used by load balancers and Kubernetes probes.
    """
    _, last_check, count = _read_state()
    return jsonify({
        "status":                   "healthy",
        "service":                  "website-health-monitor",
        "version":                  "2.0.0",
        "timestamp":                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_check_at":            last_check,
        "total_checks_completed":   count,
        "websites_configured":      len(load_websites(WEBSITES_FILE)),
        "monitor_interval_seconds": MONITOR_INTERVAL,
        "database_enabled":         _DB_MODULE_LOADED and db.DB_ENABLED if _DB_MODULE_LOADED else False,
    }), 200


@app.route("/websites", methods=["GET"])
def websites():
    """
    GET /websites
    Latest health check result for every monitored URL.
    Optional: ?status=UP or ?status=DOWN to filter.
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
    """GET /websites/<url> — Single website result."""
    results, _, _ = _read_state()
    match = next(
        (r for r in results
         if r["url"].replace("https://", "").replace("http://", "") == encoded_url),
        None,
    )
    if match:
        return jsonify(match), 200
    return jsonify({"error": f"No result found for: {encoded_url}"}), 404


@app.route("/metrics", methods=["GET"])
def metrics():
    """
    GET /metrics
    Aggregate statistics — availability %, response times, performance tiers.
    Used by Grafana dashboards and alerting rules.
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
    Recent log entries from logs.txt.
    Optional: ?limit=N (default 50, max 500)
    """
    limit   = min(request.args.get("limit", 50, type=int), 500)
    entries = read_logs(limit)
    stats   = get_log_stats()
    return jsonify({
        "log_file":         stats.get("log_file"),
        "log_file_size_kb": stats.get("log_file_size_kb"),
        "total_entries":    stats.get("total_log_entries"),
        "returned":         len(entries),
        "logs":             entries,
    }), 200


@app.route("/check", methods=["POST"])
def trigger_check():
    """
    POST /check
    Trigger an immediate on-demand health check without waiting
    for the next scheduled interval.
    """
    global _latest_results, _last_check_at, _check_count

    urls = load_websites(WEBSITES_FILE)
    if not urls:
        return jsonify({"error": "No websites configured."}), 400

    results   = check_websites_concurrent(urls)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _write_state(results, timestamp)
    write_logs_batch(results)

    # Phase 7: also write to DB on demand check
    if _DB_MODULE_LOADED and db.DB_ENABLED:
        try:
            db.log_health_checks_batch(results)
        except Exception as exc:
            print(f"[DB] Warning during /check: {exc}")

    summary                  = compute_summary(results)
    summary["triggered_at"]  = timestamp
    summary["websites"]      = results
    return jsonify(summary), 200


# ─────────────────────────────────────────────────────────────────────────────
# ── NEW PHASE 7 ROUTES (database-powered analytics) ──────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/analytics", methods=["GET"])
def analytics():
    """
    GET /analytics
    Combined analytics from MySQL: uptime %, response times, incidents, failures.

    Query parameters:
        ?hours=N   — time window in hours (default: 24)

    Example response:
        {
          "time_window_hours": 24,
          "uptime_stats": [...],
          "avg_response_times": [...],
          "downtime_incidents": [...],
          "most_failing": [...]
        }

    Industry context:
        This is the endpoint a Grafana dashboard or SLA report would call
        to build availability charts and incident timelines.
    """
    if not _DB_MODULE_LOADED or not db.DB_ENABLED:
        return jsonify({
            "error":   "Database is not enabled.",
            "message": "Set DB_ENABLED=true in .env and ensure MySQL is running.",
            "hint":    "Run: docker-compose up to start MySQL automatically.",
        }), 503

    hours = request.args.get("hours", 24, type=int)

    try:
        data = db.get_all_analytics(hours=hours)
        return jsonify(data), 200
    except Exception as exc:
        return jsonify({"error": "Analytics query failed", "detail": str(exc)}), 500


@app.route("/analytics/uptime", methods=["GET"])
def analytics_uptime():
    """
    GET /analytics/uptime
    Uptime percentage for every monitored website.

    Query parameters:
        ?hours=N   — time window in hours (default: 24)

    Example response:
        [
          {
            "url": "https://google.com",
            "total_checks": 24,
            "up_count": 24,
            "down_count": 0,
            "uptime_pct": 100.0,
            "downtime_pct": 0.0,
            "last_checked": "2026-06-16 15:00:00"
          },
          ...
        ]

    Industry context:
        This is the SLI (Service Level Indicator) — the raw metric used to
        evaluate whether you are meeting your SLO (e.g. 99.9% uptime).
        SLA violations are calculated from this data.
    """
    if not _DB_MODULE_LOADED or not db.DB_ENABLED:
        return jsonify({
            "error":   "Database is not enabled.",
            "message": "Set DB_ENABLED=true in .env and ensure MySQL is running.",
        }), 503

    hours = request.args.get("hours", 24, type=int)

    try:
        stats = db.get_uptime_stats(hours=hours)
        return jsonify({
            "time_window_hours": hours,
            "count":             len(stats),
            "uptime_stats":      stats,
        }), 200
    except Exception as exc:
        return jsonify({"error": "Uptime query failed", "detail": str(exc)}), 500


@app.route("/analytics/failures", methods=["GET"])
def analytics_failures():
    """
    GET /analytics/failures
    Two failure views in one response:
        1. Recent downtime incidents (last 24h)
        2. Most frequently failing websites (last 7 days)

    Query parameters:
        ?hours=N   — window for incidents (default: 24)
        ?days=N    — window for most_failing (default: 7)
        ?limit=N   — max incidents to return (default: 50)

    Industry context:
        This feeds incident management tools like PagerDuty and OpsGenie.
        The most_failing list shows which sites need reliability improvements.
    """
    if not _DB_MODULE_LOADED or not db.DB_ENABLED:
        return jsonify({
            "error":   "Database is not enabled.",
            "message": "Set DB_ENABLED=true in .env and ensure MySQL is running.",
        }), 503

    hours = request.args.get("hours", 24, type=int)
    days  = request.args.get("days",  7,  type=int)
    limit = request.args.get("limit", 50, type=int)

    try:
        return jsonify({
            "downtime_incidents": db.get_downtime_incidents(hours=hours, limit=limit),
            "most_failing":       db.get_most_failing(days=days),
        }), 200
    except Exception as exc:
        return jsonify({"error": "Failures query failed", "detail": str(exc)}), 500


@app.route("/history", methods=["GET"])
def history():
    """
    GET /history
    Full check history from MySQL — most recent results first.

    Query parameters:
        ?url=google.com   — filter to one website (optional)
        ?limit=N          — max rows to return (default: 100, max: 500)

    Example usage:
        GET /history                     — last 100 checks across all sites
        GET /history?url=google.com      — last 100 checks for google.com
        GET /history?limit=500           — last 500 checks across all sites

    Industry context:
        This endpoint powers the "history" or "timeline" view in monitoring
        dashboards where operators drill into a specific site's behaviour.
    """
    if not _DB_MODULE_LOADED or not db.DB_ENABLED:
        return jsonify({
            "error":   "Database is not enabled.",
            "message": "Set DB_ENABLED=true in .env and ensure MySQL is running.",
        }), 503

    url   = request.args.get("url",   None)
    limit = min(request.args.get("limit", 100, type=int), 500)

    try:
        rows = db.get_check_history(url=url, limit=limit)

        # Convert datetime objects to strings for JSON serialisation
        for row in rows:
            if row.get("checked_at") and hasattr(row["checked_at"], "strftime"):
                row["checked_at"] = row["checked_at"].strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({
            "filter_url": url,
            "limit":      limit,
            "count":      len(rows),
            "history":    rows,
        }), 200
    except Exception as exc:
        return jsonify({"error": "History query failed", "detail": str(exc)}), 500


@app.route("/db/status", methods=["GET"])
def db_status():
    """
    GET /db/status
    MySQL connection status, configuration, and table statistics.

    Returns:
        db_enabled    — whether DB_ENABLED=true in .env
        db_available  — whether MySQL server is reachable right now
        total_websites    — rows in websites table
        total_log_entries — rows in health_logs table
        monitoring_since  — earliest log entry timestamp
        last_check        — most recent log entry timestamp

    Industry context:
        Used in infrastructure dashboards to monitor the health of the
        monitoring system's own database — "monitor the monitor."
    """
    if not _DB_MODULE_LOADED:
        return jsonify({
            "db_enabled":   False,
            "db_available": False,
            "message":      "database.py module failed to load.",
        }), 503

    try:
        info = db.get_db_info()
        return jsonify(info), 200 if info.get("db_available") else 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(_err):
    return jsonify({
        "error": "Endpoint not found",
        "available_endpoints": [
            "GET  /health",
            "GET  /websites",
            "GET  /websites/<url>",
            "GET  /metrics",
            "GET  /logs?limit=N",
            "POST /check",
            "--- Phase 7 Database Endpoints ---",
            "GET  /analytics?hours=24",
            "GET  /analytics/uptime?hours=24",
            "GET  /analytics/failures?hours=24&days=7",
            "GET  /history?url=<url>&limit=100",
            "GET  /db/status",
        ],
    }), 404


@app.errorhandler(500)
def internal_error(err):
    return jsonify({"error": "Internal server error", "message": str(err)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  Website Health Monitoring System  —  REST API v2.0")
    print("=" * 62)
    print(f"  Monitor interval  : every {MONITOR_INTERVAL} seconds")
    print(f"  Websites file     : {WEBSITES_FILE}")
    print(f"  API base URL      : http://0.0.0.0:{FLASK_PORT}")
    print(f"  Database enabled  : {_DB_MODULE_LOADED and db.DB_ENABLED if _DB_MODULE_LOADED else False}")
    print("=" * 62)
    print("\n  Phase 5 Endpoints:")
    print("    GET  http://localhost:5000/health")
    print("    GET  http://localhost:5000/websites")
    print("    GET  http://localhost:5000/metrics")
    print("    GET  http://localhost:5000/logs")
    print("    POST http://localhost:5000/check")
    print("\n  Phase 7 Database Endpoints:")
    print("    GET  http://localhost:5000/analytics")
    print("    GET  http://localhost:5000/analytics/uptime")
    print("    GET  http://localhost:5000/analytics/failures")
    print("    GET  http://localhost:5000/history")
    print("    GET  http://localhost:5000/db/status")
    print("=" * 62 + "\n")

    # ── Phase 7: Initialise database on startup ───────────────────────────────
    if _DB_MODULE_LOADED and db.DB_ENABLED:
        print("[DB]  Initialising database...")
        db.init_database()

    # ── Run initial health check before starting API ──────────────────────────
    urls = load_websites(WEBSITES_FILE)
    if urls:
        print("[INFO] Running initial health check before starting API...")
        from monitor import check_websites_concurrent as _cwc
        initial_results = _cwc(urls)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_state(initial_results, ts)
        write_logs_batch(initial_results)

        if _DB_MODULE_LOADED and db.DB_ENABLED:
            saved = db.log_health_checks_batch(initial_results)
            print(f"[INFO] Initial check complete — {len(initial_results)} sites | DB: {saved} saved\n")
        else:
            print(f"[INFO] Initial check complete — {len(initial_results)} sites checked.\n")

    # ── Start background monitoring thread ────────────────────────────────────
    _start_background_monitor()

    # ── Start Flask server ────────────────────────────────────────────────────
    app.run(
        host        = "0.0.0.0",
        port        = FLASK_PORT,
        debug       = FLASK_DEBUG,
        use_reloader= False,
    )
