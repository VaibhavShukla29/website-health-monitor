# Website Health Monitoring System

A production-style website monitoring platform built with **Python**, **Flask**, and **Docker**.
Monitors website availability, measures response latency, logs monitoring history,
and exposes real-time metrics through a REST API — mimicking professional tools like
UptimeRobot, Pingdom, and Datadog Synthetic Monitoring.

---

## Features

| Feature | Description |
|---|---|
| ✅ Health Checking | HTTP availability monitoring with proper UP/DOWN classification |
| ⚡ Response Time | Latency measurement with 5-tier performance classification |
| 📋 Logging | Structured append-only audit log in logs.txt |
| 🔀 Concurrency | Parallel checking with ThreadPoolExecutor (20× speed improvement) |
| 🌐 REST API | Flask endpoints: /health · /websites · /metrics · /logs · /check |
| 🐳 Docker | Containerised with health checks, non-root security, layer caching |

---

## Architecture

```
websites.txt
     │
     ▼
monitor.py ──────────────────────────────────────────────────────┐
  load_websites()          ← reads URL list from file           │
  check_website()          ← Phase 1: HTTP request + status code│
  classify_performance()   ← Phase 2: response time tiers       │
  check_websites_concurrent() ← Phase 4: ThreadPoolExecutor     │
  compute_summary()        ← aggregate stats for API            │
     │                                                           │
     ▼                                                           │
logger.py                                                        │
  write_log()    ← append one result to logs.txt                │
  read_logs()    ← query monitoring history                     │
     │                                                           │
     ▼                                                           ▼
logs.txt                                                      app.py
  (persistent history)                                  Flask REST API
                                                        Background thread
                                                        calls monitor.py
                                                        every 60 seconds
                                                              │
                                                              ▼
                                                    HTTP endpoints on :5000
                                                    GET /health
                                                    GET /websites
                                                    GET /metrics
                                                    GET /logs
                                                    POST /check
```

---

## Project Structure

```
website-health-monitor/
├── monitor.py          Core monitoring engine (Phases 1–4)
├── app.py              Flask REST API (Phase 5)
├── logger.py           Logging module (Phase 3)
├── websites.txt        URL configuration (edit this to change what's monitored)
├── logs.txt            Monitoring history (auto-created, append-only)
├── requirements.txt    Python dependencies
├── Dockerfile          Container definition (Phase 6)
├── docker-compose.yml  Compose orchestration
├── .gitignore
├── README.md
├── screenshots/
└── docs/
    └── architecture.md
```

---

## Quick Start

### Option 1 — Run with Python directly

**Prerequisites:** Python 3.9+, pip

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/website-health-monitor.git
cd website-health-monitor

# 2. Install dependencies
pip install -r requirements.txt

# 3a. Run the CLI health checker
python monitor.py

# 3b. Or run the full REST API server
python app.py
```

### Option 2 — Run with Docker

```bash
# Build the image
docker build -t website-health-monitor .

# Run the container
docker run -p 5000:5000 website-health-monitor

# Run with custom check interval (every 30 seconds)
docker run -p 5000:5000 -e MONITOR_INTERVAL=30 website-health-monitor

# Mount your own websites.txt and persist logs
docker run -p 5000:5000 \
  -v $(pwd)/websites.txt:/app/websites.txt \
  -v $(pwd)/logs.txt:/app/logs.txt \
  website-health-monitor
```

### Option 3 — Docker Compose (recommended)

```bash
# Build and start
docker-compose up --build

# Start in background
docker-compose up -d

# View live logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## Configure Monitored Websites

Edit `websites.txt` — one URL per line:

```
# My production sites
https://my-app.com
https://api.my-app.com
https://staging.my-app.com

# Third-party dependencies
https://github.com
https://stripe.com
```

Lines starting with `#` are comments. No code changes needed — the monitor reads the file on every check cycle.

---

## CLI Output Example

```
[2026-06-01 10:15:32] Starting Website Health Monitor...
[INFO] Checking 11 URL(s) in concurrent mode...

============================================================================================
  WEBSITE HEALTH MONITOR  ·  2026-06-01 10:15:32
============================================================================================

  URL                                      STATUS     CODE     RESPONSE      PERFORMANCE
  ──────────────────────────────────────────────────────────────────────────────────────
  google.com                               ✅ UP      200      98 ms         Excellent
  github.com                               ✅ UP      200      143 ms        Acceptable
  stackoverflow.com                        ✅ UP      200      201 ms        Good
  httpbin.org/status/200                   ✅ UP      200      88 ms         Excellent
  httpbin.org/status/404                   ✅ UP      404      91 ms         Excellent
  httpbin.org/status/500                   ✅ UP      500      87 ms         Excellent
  httpbin.org/delay/3                      ✅ UP      200      3012 ms       Critical
  this-website-does-not-exist-xyz...       ❌ DOWN    Connection Failed       —
  ──────────────────────────────────────────────────────────────────────────────────────

  📊  Summary
        Monitored     : 8 website(s)
        UP / DOWN     : 7 / 1
        Availability  : 87.5%
        Response time : avg 531 ms  ·  min 87 ms  ·  max 3012 ms

  ⚠️   Slow websites (> 1000 ms):
        httpbin.org/delay/3   3012 ms — Critical

  🚨  Down websites:
        this-website-does-not-exist-xyz-abc-999.com   Connection Failed (DNS / network)
```

---

## API Endpoints

### GET /health
Service liveness check. Used by load balancers and Kubernetes probes.

```bash
curl http://localhost:5000/health
```
```json
{
  "status": "healthy",
  "service": "website-health-monitor",
  "version": "1.0.0",
  "timestamp": "2026-06-01 10:15:32",
  "last_check_at": "2026-06-01 10:15:30",
  "total_checks_completed": 5,
  "websites_configured": 11,
  "monitor_interval_seconds": 60
}
```

### GET /websites
Latest health check result for every monitored URL.

```bash
curl http://localhost:5000/websites
curl http://localhost:5000/websites?status=DOWN    # filter to DOWN only
curl http://localhost:5000/websites?status=UP      # filter to UP only
```

### GET /websites/\<url\>
Single website result.

```bash
curl http://localhost:5000/websites/google.com
curl http://localhost:5000/websites/github.com
```

### GET /metrics
Aggregate statistics for dashboards and alerting.

```bash
curl http://localhost:5000/metrics
```
```json
{
  "total": 11,
  "up": 10,
  "down": 1,
  "availability_pct": 90.91,
  "avg_response_ms": 245,
  "min_response_ms": 87,
  "max_response_ms": 3012,
  "slow_count": 1,
  "performance_tiers": {
    "excellent": 5,
    "good": 2,
    "acceptable": 1,
    "slow": 1,
    "critical": 1
  }
}
```

### GET /logs
Recent monitoring log entries.

```bash
curl http://localhost:5000/logs
curl http://localhost:5000/logs?limit=100
```

### POST /check
Trigger an immediate on-demand health check.

```bash
curl -X POST http://localhost:5000/check
```

---

## Docker Commands Reference

```bash
# Build
docker build -t website-health-monitor .
docker build -t website-health-monitor:1.0.0 .

# Run
docker run -p 5000:5000 website-health-monitor
docker run -d -p 5000:5000 --name monitor website-health-monitor   # background

# Inspect
docker ps                                  # running containers
docker logs monitor                        # container stdout
docker logs -f monitor                     # follow live logs
docker inspect website-health-monitor      # full container metadata
docker exec -it monitor /bin/bash          # shell into container

# Stop / remove
docker stop monitor
docker rm monitor
docker rmi website-health-monitor          # remove image

# Check container health
docker inspect --format='{{.State.Health.Status}}' monitor
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MONITOR_INTERVAL` | `60` | Seconds between check cycles |
| `WEBSITES_FILE` | `websites.txt` | Path to URL configuration file |
| `PORT` | `5000` | Flask server port |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |

---

## Log Format

```
2026-06-01 10:15:32 | https://google.com | UP | 200 | 98 ms | Excellent
2026-06-01 10:15:32 | https://github.com | UP | 200 | 143 ms | Acceptable
2026-06-01 10:15:33 | https://badsite.com | DOWN | Connection Failed (DNS / network)
```

---

## Performance Tiers

| Tier | Response Time | Meaning |
|---|---|---|
| Excellent | < 200 ms | Optimal — meets Google Core Web Vitals TTFB target |
| Good | 200 – 500 ms | Acceptable for most web applications |
| Acceptable | 500 ms – 1 s | Noticeable but within typical SLO thresholds |
| Slow | 1 – 2 s | Users notice; warrants investigation |
| Critical | > 2 s | Significant impact on user experience and conversions |

---

## Future Enhancements

- [ ] **Email Alerts** — notify on downtime via SMTP / SendGrid
- [ ] **Slack / Telegram Alerts** — webhook-based incident notifications
- [ ] **Prometheus Metrics** — `/metrics` endpoint in Prometheus format for Grafana
- [ ] **Grafana Dashboard** — pre-built dashboard JSON for visualisation
- [ ] **PostgreSQL / InfluxDB** — replace flat-file logging with time-series DB
- [ ] **Kubernetes Deployment** — Helm chart with ConfigMap for websites.txt
- [ ] **AWS EC2 / ECS Deployment** — Terraform/CloudFormation template
- [ ] **GitHub Actions CI/CD** — automated test + Docker build + push pipeline
- [ ] **Authentication** — API key middleware for the Flask endpoints
- [ ] **Multi-region Checking** — deploy probes in multiple geographies

---

## Resume Points

> **Website Health Monitoring System** | Python · Flask · Docker · Git

- Developed a monitoring platform that continuously checks website availability and response latency across multiple endpoints, mimicking the core functionality of UptimeRobot and Datadog Synthetic Monitoring.
- Implemented concurrent health checks using `ThreadPoolExecutor` (20 parallel threads), reducing check cycle time by ~20× compared to sequential execution.
- Built a REST API using Flask exposing real-time monitoring data (`/health`, `/websites`, `/metrics`, `/logs`) consumed by dashboards and alerting systems.
- Designed structured append-only logging for incident audit trails, aligned with ELK Stack ingestion formats.
- Containerised the application using Docker with layer-caching optimisation, non-root user security, and integrated HEALTHCHECK — production deployment best practices.
- Applied Twelve-Factor App methodology: externalised configuration via environment variables for portable deployment across local, Docker, and cloud environments.

---

## Interview Topics Covered

| Topic | Where demonstrated |
|---|---|
| HTTP / HTTPS / DNS | monitor.py — exception hierarchy |
| Status codes | check_website() UP/DOWN logic |
| Latency / SLI / SLO | Phase 2 performance tiers |
| Logging & observability | logger.py |
| Concurrency / threads | check_websites_concurrent() |
| REST API design | app.py routes |
| Containerisation | Dockerfile |
| Docker layer caching | Dockerfile comments |
| Environment-based config | os.environ.get() pattern |
| Thread safety | threading.Lock() in app.py |
| Graceful error handling | 5 specific exception types |
| Separation of concerns | monitor / logger / app split |

---

## Author

Built as a DevOps/CloudOps portfolio project.
Demonstrates monitoring, REST APIs, logging, concurrency, and Docker containerisation.
