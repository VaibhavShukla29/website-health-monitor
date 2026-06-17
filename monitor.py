"""
monitor.py  —  Core Monitoring Engine  (Phases 1–4 + Phase 7 DB integration)
=============================================================================
Phase 1 : Health checker  — HTTP requests, status codes, error handling
Phase 2 : Response time   — latency measurement, performance tiers
Phase 3 : Integration     — results returned to logger and Flask API
Phase 4 : Concurrency     — ThreadPoolExecutor for parallel checking
Phase 7 : Database        — saves every result to MySQL via database.py

What changed in Phase 7:
    - Imported database module
    - init_database() called on startup to create tables if needed
    - log_health_checks_batch() called after every check cycle
    - All existing functionality is completely unchanged
"""

import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Phase 7: Import database module ──────────────────────────────────────────
# Import is wrapped in a try/except so monitor.py still works even if
# database.py has an import error (e.g. PyMySQL not installed)
try:
    import database as db
    _DB_MODULE_LOADED = True
except Exception as _db_import_err:
    _DB_MODULE_LOADED = False
    print(f"[WARN] database.py could not be loaded: {_db_import_err}")


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

TIMEOUT_SECONDS = 10
STATUS_UP       = "UP"
STATUS_DOWN     = "DOWN"
MAX_WORKERS     = 20
SLOW_THRESHOLD  = 1000


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — PERFORMANCE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_performance(ms: int) -> str:
    if ms is None:
        return "N/A"
    if ms < 200:
        return "Excellent"
    if ms < 500:
        return "Good"
    if ms < 1000:
        return "Acceptable"
    if ms < 2000:
        return "Slow"
    return "Critical"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — LOAD WEBSITES FROM FILE
# ─────────────────────────────────────────────────────────────────────────────

def load_websites(filepath: str = "websites.txt") -> list:
    """
    Read URLs from a plain-text file into a Python list.
    Lines starting with '#' are comments. Empty lines are ignored.
    """
    websites = []
    try:
        with open(filepath, "r") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    websites.append(url)
    except FileNotFoundError:
        print(f"[ERROR] File not found: '{filepath}'")
    except PermissionError:
        print(f"[ERROR] Permission denied reading: '{filepath}'")
    return websites


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 + 2 — SINGLE WEBSITE HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_website(url: str) -> dict:
    """
    Perform one complete health check on a single URL.

    Returns a dict with all check details.
    Status defaults to DOWN — the site must prove it is UP.
    Any HTTP response (200, 404, 500) counts as UP.
    Unreachable server (DNS fail, timeout) counts as DOWN.
    """
    result = {
        "url":              url,
        "status":           STATUS_DOWN,
        "status_code":      None,
        "response_time_ms": None,
        "performance":      "N/A",
        "error":            None,
        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        start    = datetime.now()
        response = requests.get(
            url,
            timeout        = TIMEOUT_SECONDS,
            allow_redirects= True,
            headers        = {"User-Agent": "WebsiteHealthMonitor/1.0"},
        )
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)

        result.update({
            "status":           STATUS_UP,
            "status_code":      response.status_code,
            "response_time_ms": elapsed_ms,
            "performance":      classify_performance(elapsed_ms),
        })

    except requests.exceptions.SSLError:
        result["error"] = "SSL Certificate Error"
    except requests.exceptions.ConnectionError:
        result["error"] = "Connection Failed (DNS / network)"
    except requests.exceptions.Timeout:
        result["error"] = f"Timeout (> {TIMEOUT_SECONDS}s)"
    except requests.exceptions.TooManyRedirects:
        result["error"] = "Too Many Redirects"
    except requests.exceptions.MissingSchema:
        result["error"] = "Invalid URL — missing https://"
    except requests.exceptions.InvalidURL:
        result["error"] = "Invalid URL Format"
    except requests.exceptions.RequestException as exc:
        result["error"] = f"Request Error: {str(exc)[:60]}"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — CONCURRENT CHECKING
# ─────────────────────────────────────────────────────────────────────────────

def check_websites_concurrent(urls: list, max_workers: int = MAX_WORKERS) -> list:
    """
    Check multiple URLs simultaneously using a thread pool.

    ThreadPoolExecutor creates a pool of worker threads.
    executor.submit() schedules each URL check in a thread.
    as_completed() yields results as threads finish (fastest first).
    Final list is sorted by URL for consistent output.
    """
    if not urls:
        return []

    workers = min(max_workers, len(urls))
    results = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_url = {
            executor.submit(check_website, url): url
            for url in urls
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "url":              url,
                    "status":           STATUS_DOWN,
                    "status_code":      None,
                    "response_time_ms": None,
                    "performance":      "N/A",
                    "error":            f"Thread error: {str(exc)[:50]}",
                    "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

    results.sort(key=lambda r: r["url"])
    return results


def check_websites_sequential(urls: list) -> list:
    """Sequential fallback for debugging or very small URL lists."""
    return [check_website(url) for url in urls]


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY RESULTS TABLE
# ─────────────────────────────────────────────────────────────────────────────

def display_results(results: list) -> None:
    """Print a formatted health report to stdout."""
    if not results:
        print("[INFO] No results to display.")
        return

    sorted_results = sorted(
        results,
        key=lambda r: (
            r["status"] == STATUS_UP,
            -(r["response_time_ms"] or 0),
        )
    )

    print("\n" + "=" * 92)
    print(f"  WEBSITE HEALTH MONITOR  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 92)
    print(f"\n  {'URL':<40} {'STATUS':<10} {'CODE':<8} {'RESPONSE':<14} PERFORMANCE")
    print("  " + "─" * 86)

    for r in sorted_results:
        url_display = r["url"].replace("https://", "").replace("http://", "")
        if len(url_display) > 38:
            url_display = url_display[:35] + "..."

        status_icon = "✅ UP  " if r["status"] == STATUS_UP else "❌ DOWN"

        if r["status_code"] is not None:
            code_col = str(r["status_code"])
        elif r["error"]:
            code_col = r["error"][:16]
        else:
            code_col = "N/A"

        time_col = f"{r['response_time_ms']} ms" if r["response_time_ms"] else "—"
        perf_col = r.get("performance", "N/A")

        print(f"  {url_display:<40} {status_icon:<10} {code_col:<8} {time_col:<14} {perf_col}")

    print("  " + "─" * 86)

    total  = len(results)
    up     = sum(1 for r in results if r["status"] == STATUS_UP)
    down   = total - up
    avail  = (up / total * 100) if total else 0.0
    times  = [r["response_time_ms"] for r in results if r["response_time_ms"]]
    avg_ms = int(sum(times) / len(times)) if times else 0
    min_ms = min(times) if times else 0
    max_ms = max(times) if times else 0
    slow   = [r for r in results if r["response_time_ms"]
              and r["response_time_ms"] > SLOW_THRESHOLD]

    print(f"\n  📊  Summary")
    print(f"       Monitored     : {total} website(s)")
    print(f"       UP / DOWN     : {up} / {down}")
    print(f"       Availability  : {avail:.1f}%")
    if times:
        print(f"       Response time : avg {avg_ms} ms  ·  "
              f"min {min_ms} ms  ·  max {max_ms} ms")

    if slow:
        print(f"\n  ⚠️   Slow websites (> {SLOW_THRESHOLD} ms):")
        for s in slow:
            su = s["url"].replace("https://", "").replace("http://", "")
            print(f"       {su:<40} {s['response_time_ms']} ms  — {s.get('performance','')}")

    if down:
        print(f"\n  🚨  Down websites:")
        for d in [r for r in results if r["status"] == STATUS_DOWN]:
            du = d["url"].replace("https://", "").replace("http://", "")
            print(f"       {du:<40} {d.get('error', 'Unknown error')}")

    print("=" * 92 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# COMPUTE SUMMARY DICT (used by Flask API)
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary(results: list) -> dict:
    """Return aggregate stats as a dict for JSON serialisation."""
    if not results:
        return {"total": 0, "up": 0, "down": 0, "availability_pct": 0.0}

    total = len(results)
    up    = sum(1 for r in results if r["status"] == STATUS_UP)
    times = [r["response_time_ms"] for r in results if r["response_time_ms"]]

    return {
        "total":             total,
        "up":                up,
        "down":              total - up,
        "availability_pct":  round((up / total * 100), 2) if total else 0.0,
        "avg_response_ms":   int(sum(times) / len(times)) if times else None,
        "min_response_ms":   min(times) if times else None,
        "max_response_ms":   max(times) if times else None,
        "slow_count":        sum(1 for t in times if t > SLOW_THRESHOLD),
        "performance_tiers": {
            "excellent":  sum(1 for t in times if t < 200),
            "good":       sum(1 for t in times if 200 <= t < 500),
            "acceptable": sum(1 for t in times if 500 <= t < 1000),
            "slow":       sum(1 for t in times if 1000 <= t < 2000),
            "critical":   sum(1 for t in times if t >= 2000),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_health_check(
    websites_file: str = "websites.txt",
    concurrent:    bool = True
) -> list:
    """
    Top-level orchestrator: load → check → display → save to DB → return.

    Phase 7 addition:
        After collecting results, saves them to MySQL if DB is enabled.
        If the DB save fails, the error is logged but does NOT stop
        the function from returning results normally.

    Args:
        websites_file : path to URL configuration file
        concurrent    : True = parallel threads, False = sequential

    Returns:
        list of result dicts
    """

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
          f"Starting Website Health Monitor...")

    # ── Phase 7: Initialise database on startup ───────────────────────────────
    if _DB_MODULE_LOADED and db.DB_ENABLED:
        db.init_database()

    urls = load_websites(websites_file)
    if not urls:
        print("[WARN] No URLs loaded. Populate 'websites.txt' and retry.")
        return []

    mode = "concurrent" if concurrent else "sequential"
    print(f"[INFO] Checking {len(urls)} URL(s) in {mode} mode...\n")

    # ── Run health checks ─────────────────────────────────────────────────────
    if concurrent:
        results = check_websites_concurrent(urls)
    else:
        results = check_websites_sequential(urls)

    # ── Display formatted table ───────────────────────────────────────────────
    display_results(results)

    # ── Phase 7: Save results to MySQL ────────────────────────────────────────
    if _DB_MODULE_LOADED and db.DB_ENABLED:
        try:
            saved = db.log_health_checks_batch(results)
            print(f"[DB]   {saved}/{len(results)} results saved to MySQL")
        except Exception as exc:
            # DB failure must NEVER crash the monitoring loop
            print(f"[DB]   Warning: Could not save to database: {exc}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_health_check()
