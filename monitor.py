"""
monitor.py  —  Core Monitoring Engine  (Phases 1 – 4)
======================================================
Phase 1 : Health checker  — HTTP requests, status codes, error handling
Phase 2 : Response time   — latency measurement, performance tiers, sorting
Phase 3 : Integration     — results returned to logger and Flask API
Phase 4 : Concurrency     — ThreadPoolExecutor for parallel checking

Industry equivalent: the "probe" component in UptimeRobot, Pingdom,
Datadog Synthetic Monitoring, and AWS CloudWatch Synthetics.
"""

import requests                                      # HTTP client library
from datetime import datetime                        # Timestamps
from concurrent.futures import ThreadPoolExecutor, as_completed   # Phase 4


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# Centralising magic values so you change them in one place, not scattered
# across the codebase. This is the DRY principle (Don't Repeat Yourself).
# ─────────────────────────────────────────────────────────────────────────────

TIMEOUT_SECONDS  = 10      # Max seconds to wait for a server response
STATUS_UP        = "UP"    # Server responded (any HTTP status)
STATUS_DOWN      = "DOWN"  # Server unreachable (network/DNS/timeout failure)
MAX_WORKERS      = 20      # Maximum parallel threads in the pool
SLOW_THRESHOLD   = 1000    # Response time (ms) above which a site is "slow"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — PERFORMANCE CLASSIFICATION
# Real monitoring systems (Datadog, New Relic) use performance tiers to
# colour-code dashboards.  These thresholds align with Google's Core Web Vitals
# guidance and typical SLO targets used in the industry.
# ─────────────────────────────────────────────────────────────────────────────

def classify_performance(ms: int) -> str:
    """
    Map a response time (milliseconds) to a human-readable performance tier.

    Thresholds are based on real-world SLO standards:
        < 200 ms   — Excellent  (Google recommends < 200ms for TTFB)
        < 500 ms   — Good       (acceptable for most web apps)
        < 1000 ms  — Acceptable (1 second is a common SLO threshold)
        < 2000 ms  — Slow       (users notice delays > 1s noticeably)
        >= 2000 ms — Critical   (2+ seconds causes significant user drop-off)
    """
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
# Separating configuration (what to monitor) from logic (how to monitor)
# is a core DevOps practice.  URLs live in websites.txt so you can change
# the monitored set without touching Python code.
# ─────────────────────────────────────────────────────────────────────────────

def load_websites(filepath: str = "websites.txt") -> list:
    """
    Read URLs from a plain-text file into a Python list.

    File format:
        - One URL per line
        - Lines starting with '#' are comments (ignored)
        - Empty lines are ignored
        - Full URL required: https://example.com (not just example.com)

    Returns:
        list of URL strings (empty list on any file error)
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
        print(f"[INFO]  Create '{filepath}' with one URL per line.")
    except PermissionError:
        print(f"[ERROR] Permission denied reading: '{filepath}'")
    return websites


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 + 2 — SINGLE WEBSITE HEALTH CHECK
# This is the core function of the entire system.  Everything else is
# orchestration, presentation, or persistence around this single operation.
# ─────────────────────────────────────────────────────────────────────────────

def check_website(url: str) -> dict:
    """
    Perform one complete health check on a single URL.

    Design decisions:
        FAIL-SAFE DEFAULT  — result starts as DOWN.  The site must actively
                             prove it is UP.  Any unhandled code path leaves
                             the result as DOWN rather than falsely UP.

        RETURNS A DICT     — not a string, not a print statement.  The dict
                             format works identically in:
                               • CLI display (Phase 1)
                               • Log files   (Phase 3)
                               • JSON API    (Phase 5)
                               • Threads     (Phase 4)
                             This is the single-responsibility principle.

        UP vs DOWN logic   — ANY HTTP response (200, 404, 500, etc.) is UP
                             because the infrastructure responded.  DOWN means
                             the network/DNS/server is completely unreachable.

    Returns:
        dict with keys: url, status, status_code, response_time_ms,
                        performance, error, timestamp
    """

    # Fail-safe default — DOWN until proven UP
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
        # ── Phase 2: Record exact start time ─────────────────────────────
        start = datetime.now()

        # ── Phase 1: Send the HTTP GET request ───────────────────────────
        response = requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            allow_redirects=True,            # Follow 301/302 redirects automatically
            headers={"User-Agent": "WebsiteHealthMonitor/1.0"},
        )

        # ── Phase 2: Calculate elapsed time in milliseconds ───────────────
        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)

        # ── SUCCESS — update result with real data ─────────────────────────
        result.update({
            "status":           STATUS_UP,
            "status_code":      response.status_code,
            "response_time_ms": elapsed_ms,
            "performance":      classify_performance(elapsed_ms),
        })

    # ── Exception hierarchy: specific first, generic last ─────────────────
    # Each exception type gives an operator different diagnostic information.
    # Order matters — Python evaluates except clauses top to bottom.

    except requests.exceptions.SSLError:
        # Expired/invalid/self-signed TLS certificate
        # From a user perspective this makes the site inaccessible
        result["error"] = "SSL Certificate Error"

    except requests.exceptions.ConnectionError:
        # DNS lookup failed, connection refused, or no network route
        result["error"] = "Connection Failed (DNS / network)"

    except requests.exceptions.Timeout:
        # Server took longer than TIMEOUT_SECONDS to respond
        result["error"] = f"Timeout (> {TIMEOUT_SECONDS}s)"

    except requests.exceptions.TooManyRedirects:
        # Redirect loop detected (http → https → http → ...)
        result["error"] = "Too Many Redirects"

    except requests.exceptions.MissingSchema:
        # URL missing http:// or https:// prefix
        result["error"] = "Invalid URL — missing https://"

    except requests.exceptions.InvalidURL:
        # Malformed URL that the library can't parse
        result["error"] = "Invalid URL Format"

    except requests.exceptions.RequestException as exc:
        # Catch-all for any requests exception not handled above
        result["error"] = f"Request Error: {str(exc)[:60]}"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — CONCURRENT WEBSITE CHECKING
#
# Without concurrency:  N sites × ~1s each = N seconds total
# With concurrency:     N sites ÷ MAX_WORKERS threads ≈ 1 second total
#
# Example with 100 sites and 20 threads:
#   Sequential:  100 × 1s = 100 seconds
#   Concurrent:  100 ÷ 20 = ~5 seconds  (20× faster)
#
# WHY THREADS AND NOT PROCESSES?
#   Health checking is I/O-bound — we spend time WAITING for network
#   responses, not doing CPU computation.  Python's GIL (Global Interpreter
#   Lock) does not hinder threads during I/O waits.  Threads share memory
#   (no need to serialise results) and are lighter than processes.
#   Use processes for CPU-bound tasks (image processing, ML inference).
# ─────────────────────────────────────────────────────────────────────────────

def check_websites_concurrent(urls: list, max_workers: int = MAX_WORKERS) -> list:
    """
    Check multiple URLs simultaneously using a thread pool.

    ThreadPoolExecutor manages a pool of worker threads.
    executor.submit(fn, arg) schedules fn(arg) to run in a thread.
    as_completed() yields Future objects as threads finish (fastest first).

    The results are sorted by URL for consistent ordering across runs.
    """
    if not urls:
        return []

    workers = min(max_workers, len(urls))  # Don't create more threads than URLs
    results = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Map each URL to its Future (a handle to the pending result)
        future_to_url = {
            executor.submit(check_website, url): url
            for url in urls
        }

        # Collect results as threads complete
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results.append(future.result())
            except Exception as exc:
                # If the thread itself crashes (shouldn't happen with our
                # exception handling, but defensive programming is good)
                results.append({
                    "url": url, "status": STATUS_DOWN,
                    "status_code": None, "response_time_ms": None,
                    "performance": "N/A", "error": f"Thread error: {str(exc)[:50]}",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

    # Sort for deterministic output — same URL list always in same order
    results.sort(key=lambda r: r["url"])
    return results


def check_websites_sequential(urls: list) -> list:
    """
    Sequential fallback — useful for debugging or very small URL lists.
    Also used to demonstrate the speed difference vs concurrent in Phase 4.
    """
    return [check_website(url) for url in urls]


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — DISPLAY FORMATTED RESULTS TABLE
# ─────────────────────────────────────────────────────────────────────────────

def display_results(results: list) -> None:
    """
    Print a formatted health report table to stdout.

    Sorted by: DOWN first (most urgent), then slowest → fastest within UP.
    This mimics how production monitoring dashboards surface problems first.
    """
    if not results:
        print("[INFO] No results to display.")
        return

    # Sort: DOWN sites first; among UP sites, slowest first
    sorted_results = sorted(
        results,
        key=lambda r: (
            r["status"] == STATUS_UP,               # False (0) sorts before True (1)
            -(r["response_time_ms"] or 0),           # Slowest (highest ms) first
        )
    )

    print("\n" + "=" * 92)
    print(f"  WEBSITE HEALTH MONITOR  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 92)
    print(f"\n  {'URL':<40} {'STATUS':<10} {'CODE':<8} {'RESPONSE':<14} PERFORMANCE")
    print("  " + "─" * 86)

    for r in sorted_results:
        # Shorten URL for display (remove protocol prefix, truncate if long)
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

        time_col = f"{r['response_time_ms']} ms" if r["response_time_ms"] is not None else "—"
        perf_col = r.get("performance", "N/A")

        print(f"  {url_display:<40} {status_icon:<10} {code_col:<8} {time_col:<14} {perf_col}")

    print("  " + "─" * 86)

    # ── Summary statistics (Phase 2) ──────────────────────────────────────
    total   = len(results)
    up      = sum(1 for r in results if r["status"] == STATUS_UP)
    down    = total - up
    avail   = (up / total * 100) if total else 0.0
    times   = [r["response_time_ms"] for r in results if r["response_time_ms"] is not None]
    avg_ms  = int(sum(times) / len(times)) if times else 0
    min_ms  = min(times) if times else 0
    max_ms  = max(times) if times else 0
    slow    = [r for r in results if r["response_time_ms"] and r["response_time_ms"] > SLOW_THRESHOLD]

    print(f"\n  📊  Summary")
    print(f"       Monitored     : {total} website(s)")
    print(f"       UP / DOWN     : {up} / {down}")
    print(f"       Availability  : {avail:.1f}%")
    if times:
        print(f"       Response time : avg {avg_ms} ms  ·  min {min_ms} ms  ·  max {max_ms} ms")

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
# COMPUTE SUMMARY DICT  (used by Flask API — Phase 5)
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary(results: list) -> dict:
    """
    Return aggregate statistics as a dict suitable for JSON serialisation.
    Used by the /metrics API endpoint and background monitoring thread.
    """
    if not results:
        return {"total": 0, "up": 0, "down": 0, "availability_pct": 0.0}

    total = len(results)
    up    = sum(1 for r in results if r["status"] == STATUS_UP)
    times = [r["response_time_ms"] for r in results if r["response_time_ms"] is not None]

    return {
        "total":            total,
        "up":               up,
        "down":             total - up,
        "availability_pct": round((up / total * 100), 2) if total else 0.0,
        "avg_response_ms":  int(sum(times) / len(times)) if times else None,
        "min_response_ms":  min(times) if times else None,
        "max_response_ms":  max(times) if times else None,
        "slow_count":       sum(1 for t in times if t > SLOW_THRESHOLD),
        "performance_tiers": {
            "excellent":   sum(1 for t in times if t < 200),
            "good":        sum(1 for t in times if 200 <= t < 500),
            "acceptable":  sum(1 for t in times if 500 <= t < 1000),
            "slow":        sum(1 for t in times if 1000 <= t < 2000),
            "critical":    sum(1 for t in times if t >= 2000),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_health_check(websites_file: str = "websites.txt", concurrent: bool = True) -> list:
    """
    Top-level orchestrator: loads → checks → displays → returns results.

    Args:
        websites_file : path to the URL configuration file
        concurrent    : True = ThreadPoolExecutor (Phase 4), False = sequential
    Returns:
        list of result dicts (for logging, API, or further processing)
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
          f"Starting Website Health Monitor...")

    urls = load_websites(websites_file)
    if not urls:
        print("[WARN] No URLs loaded. Populate 'websites.txt' and retry.")
        return []

    mode = "concurrent" if concurrent else "sequential"
    print(f"[INFO] Checking {len(urls)} URL(s) in {mode} mode...\n")

    if concurrent:
        results = check_websites_concurrent(urls)
    else:
        results = check_websites_sequential(urls)

    display_results(results)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# Guard ensures run_health_check() only fires when this file is executed
# directly (python monitor.py), NOT when imported by app.py or logger.py.
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_health_check()
