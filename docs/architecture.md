# Architecture — Website Health Monitoring System

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Docker Container                            │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ websites.txt │───▶│  monitor.py  │───▶│     logger.py        │  │
│  │  URL config  │    │  Core engine │    │  Structured logging  │  │
│  └──────────────┘    └──────┬───────┘    └──────────┬───────────┘  │
│                             │                       │              │
│                             │ results list          │ append       │
│                             ▼                       ▼              │
│                      ┌──────────────┐       ┌──────────────┐       │
│                      │   app.py     │       │   logs.txt   │       │
│                      │ Flask API    │       │  Audit trail │       │
│                      │ Background   │       └──────────────┘       │
│                      │ thread loop  │                              │
│                      └──────┬───────┘                              │
│                             │ HTTP :5000                           │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   API Consumers    │
                    │  • Browser/curl    │
                    │  • Grafana         │
                    │  • PagerDuty       │
                    │  • CI/CD pipeline  │
                    └────────────────────┘
```

## Data Flow

```
1. Background thread wakes (every MONITOR_INTERVAL seconds)
        │
        ▼
2. load_websites("websites.txt")
   → returns ["https://google.com", "https://github.com", ...]
        │
        ▼
3. check_websites_concurrent(urls)
   ┌───────────────────────────────────────────┐
   │  ThreadPoolExecutor (20 threads)          │
   │  Thread 1: check_website("google.com")   │
   │  Thread 2: check_website("github.com")   │
   │  Thread N: check_website("...")          │
   │  → all run in parallel                   │
   │  → as_completed() collects results       │
   └───────────────────────────────────────────┘
        │
        ▼
4. results = [
     {"url": "https://google.com", "status": "UP",
      "status_code": 200, "response_time_ms": 98,
      "performance": "Excellent", "error": null, ...},
     ...
   ]
        │
        ├──▶ _write_state(results, timestamp)   [shared memory, thread-safe]
        │
        └──▶ write_logs_batch(results)          [appends to logs.txt]

5. Flask route GET /websites
   → _read_state()   [thread-safe read of shared memory]
   → return jsonify(results)
```

## Module Responsibilities

### monitor.py — Core Engine
- **load_websites()** — reads URL list from file, handles file errors
- **check_website()** — single HTTP health check with response time measurement
- **classify_performance()** — maps ms → performance tier label
- **check_websites_concurrent()** — ThreadPoolExecutor parallel checking
- **display_results()** — formatted CLI table output
- **compute_summary()** — aggregate stats dict for API
- **run_health_check()** — orchestrator for CLI usage

### logger.py — Persistence Layer
- **_get_logger()** — singleton Python logger with file handler
- **write_log()** — appends one result to logs.txt
- **write_logs_batch()** — appends a full check cycle
- **read_logs()** — retrieves last N log entries
- **get_log_stats()** — aggregate log statistics

### app.py — API Layer
- **_monitoring_loop()** — background daemon thread, runs forever
- **_start_background_monitor()** — launches daemon thread on startup
- **GET /health** — service liveness
- **GET /websites** — latest results with optional status filter
- **GET /websites/<url>** — single site detail
- **GET /metrics** — aggregate statistics
- **GET /logs** — log history with pagination
- **POST /check** — on-demand immediate check

## Thread Safety Design

```
Background Thread                  Flask Request Thread(s)
      │                                     │
      │  check_websites_concurrent()        │  GET /websites
      │  → results = [...]                  │
      │                                     │
      │  with _lock:          ◀─────────────│── _lock.acquire()
      │      _latest_results = results      │  (blocks until lock released)
      │      _last_check_at = timestamp     │
      │  _lock.release()  ───────────────── │  
      │                                     │  _latest_results (safe copy)
      │                                     │  return jsonify(...)
```

`threading.Lock()` ensures only one thread reads or writes `_latest_results`
at a time, preventing race conditions where a read sees a half-written list.

## Key Design Decisions

### 1. Why UP for 4xx/5xx responses?
`STATUS_UP` means the **infrastructure** is reachable.
`STATUS_DOWN` means the **network** is broken.
A 404 means the server received the request — infrastructure is healthy.
A 500 means the application has a bug — but the server is running.
This matches the semantics of UptimeRobot, Pingdom, and Datadog.

### 2. Why ThreadPoolExecutor over asyncio?
`requests` is a synchronous (blocking) library.
Using asyncio with blocking I/O defeats its purpose.
Threads are appropriate for I/O-bound work with synchronous libraries.
For a pure asyncio solution you'd use `aiohttp` instead of `requests`.

### 3. Why flat-file logging instead of a database?
Simplicity — zero infrastructure dependency, works anywhere Python runs.
In production you'd add:
- PostgreSQL for queryable history
- InfluxDB/TimescaleDB for time-series analysis
- Elasticsearch for full-text log search
The flat file is a starting point with the same write/read API contract.

### 4. Why `if __name__ == "__main__":` guard in monitor.py?
Prevents `run_health_check()` from firing when app.py imports monitor.py.
Without the guard: `from monitor import check_website` → full health check runs.
With the guard: import works cleanly, function only runs on direct execution.

## Scaling Path

| Scale | Architecture |
|---|---|
| 10–100 URLs | This implementation — single process, single host |
| 100–1,000 URLs | Increase MAX_WORKERS; add Redis for shared state |
| 1,000–10,000 URLs | Multiple checker workers behind a message queue (Celery + Redis) |
| 10,000+ URLs | Distributed probes in multiple regions; time-series DB; Kubernetes |
