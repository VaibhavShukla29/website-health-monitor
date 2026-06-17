# Website Health Monitoring System v2.0

A production-style website monitoring platform built with **Python**, **Flask**, **MySQL**, and **Docker**.
Monitors website availability, measures response latency, stores monitoring history in MySQL,
and exposes real-time analytics through a REST API — mimicking professional tools like
UptimeRobot, Pingdom, and Datadog Synthetic Monitoring.

---

## What's New in v2.0

| Feature | Description |
|---|---|
| 🗄️ MySQL Database | Every health check result persisted to MySQL automatically |
| 📊 Uptime Analytics | SLI metrics — uptime % per website from SQL aggregations |
| 📈 Response Analytics | Average, min, max response times with performance tiers |
| 🚨 Failure Tracking | Downtime incidents and most frequently failing websites |
| 📜 Full History | Complete check history queryable from MySQL |
| 🔌 DB Status API | Monitor the monitoring system's own database health |

---

## Features

| Feature | Description |
|---|---|
| ✅ Health Checking | HTTP availability monitoring with proper UP/DOWN classification |
| ⚡ Response Time | Latency measurement with 5-tier performance classification |
| 📋 File Logging | Structured append-only audit log in logs.txt |
| 🔀 Concurrency | Parallel checking with ThreadPoolExecutor (20× speed improvement) |
| 🗄️ MySQL Storage | Persistent monitoring history with normalized schema |
| 🌐 REST API | 11 endpoints covering health, metrics, analytics, and history |
| 🐳 Docker | Full stack containerisation — app + MySQL in Docker Compose |

---

## Architecture

```
websites.txt
     │
     ▼
monitor.py ──────────────────────────────────────────────────────────────┐
  load_websites()          ← reads URL list from file                   │
  check_website()          ← HTTP request + status code + response time │
  classify_performance()   ← response time tier (Excellent → Critical)  │
  check_websites_concurrent() ← 20 parallel threads                     │
  compute_summary()        ← aggregate stats for API                    │
     │                                                                   │
     ├──▶ logger.py  ──▶  logs.txt (append-only audit trail)            │
     │                                                                   │
     └──▶ database.py ──▶  MySQL                                         │
              get_or_create_website()   ← upsert into websites table    │
              log_health_checks_batch() ← insert into health_logs       │
              get_uptime_stats()        ← SLI analytics query           │
              get_avg_response_times()  ← performance analytics         │
              get_downtime_incidents()  ← incident investigation        │
              get_most_failing()        ← reliability ranking           │
              get_check_history()       ← full timeline query           │
                                                                         │
app.py  ─────────────────────────────────────────────────────────────────┘
  Background thread calls monitor.py every 60 seconds
  Flask serves 11 REST API endpoints on port 5000
       │
       ▼
  REST API (:5000)
  ├── GET /health                  Service liveness
  ├── GET /websites                Latest check results
  ├── GET /websites/<url>          Single website result
  ├── GET /metrics                 Aggregate statistics
  ├── GET /logs                    File-based log history
  ├── POST /check                  On-demand check
  ├── GET /analytics               Combined DB analytics
  ├── GET /analytics/uptime        Uptime % per website (SLI)
  ├── GET /analytics/failures      Incidents + most failing
  ├── GET /history                 Full MySQL check history
  └── GET /db/status               Database connection status
```

---

## Database Schema

```sql
-- Master list of monitored URLs
CREATE TABLE websites (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    url         VARCHAR(500) NOT NULL,
    name        VARCHAR(255),
    is_active   TINYINT(1) DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_url (url)
);

-- Every health check result
CREATE TABLE health_logs (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    website_id       INT NOT NULL,
    status           VARCHAR(10) NOT NULL,       -- UP | DOWN
    status_code      SMALLINT,                   -- 200, 404, 500, etc.
    response_time_ms INT,                        -- milliseconds
    performance      VARCHAR(20),                -- Excellent/Good/Slow/Critical
    error_message    VARCHAR(500),               -- failure reason if DOWN
    checked_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE CASCADE,
    INDEX idx_website_id (website_id),
    INDEX idx_checked_at (checked_at),
    INDEX idx_status (status)
);
```

---

## Project Structure

```
website-health-monitor/
├── monitor.py          Core monitoring engine (Phases 1–4 + DB writes)
├── app.py              Flask REST API — 11 endpoints (Phase 5 + DB analytics)
├── logger.py           File-based logging module (Phase 3)
├── database.py         MySQL database layer (Phase 7) ← NEW
├── schema.sql          Database schema — CREATE TABLE statements ← NEW
├── queries.sql         Analytics SQL queries reference ← NEW
├── websites.txt        URL configuration (edit to change monitored sites)
├── logs.txt            File-based monitoring history (auto-created)
├── .env.example        Environment variables template ← NEW
├── .env                Your actual credentials (gitignored) ← NEW
├── requirements.txt    Python dependencies (includes PyMySQL + python-dotenv)
├── Dockerfile          Container definition
├── docker-compose.yml  Full stack: Flask app + MySQL (updated) ← UPDATED
├── .gitignore
├── README.md
├── screenshots/
└── docs/
    └── architecture.md
```

---

## Quick Start

### Option 1 — Python only (no database)

```bash
# 1. Clone repository
git clone https://github.com/VaibhavShukla29/website-health-monitor.git
cd website-health-monitor

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file
copy .env.example .env       # Windows
cp .env.example .env         # Mac/Linux
# Leave DB_ENABLED=false for file-only mode

# 5. Run health checker
python monitor.py

# 6. Run REST API
python app.py
```

### Option 2 — Docker Compose (full stack with MySQL) ← Recommended

```bash
# 1. Clone repository
git clone https://github.com/VaibhavShukla29/website-health-monitor.git
cd website-health-monitor

# 2. Build and start everything (Flask + MySQL)
docker compose up --build

# 3. Test the API
curl http://localhost:5000/health
curl http://localhost:5000/db/status
curl http://localhost:5000/analytics/uptime
```

Everything starts automatically — MySQL initialises, tables are created, monitoring begins, and results flow into the database every 60 seconds.

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|---|---|---|
| `DB_ENABLED` | `false` | Set `true` to activate MySQL storage |
| `DB_HOST` | `localhost` | MySQL host (`mysql` inside Docker) |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `health_monitor` | Database name |
| `DB_USER` | `monitor_user` | MySQL username |
| `DB_PASSWORD` | `monitor_pass` | MySQL password |
| `MONITOR_INTERVAL` | `60` | Seconds between check cycles |
| `WEBSITES_FILE` | `websites.txt` | URL configuration file path |
| `PORT` | `5000` | Flask server port |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |

---

## Configure Monitored Websites

Edit `websites.txt` — one URL per line:

```
# Production sites
https://my-app.com
https://api.my-app.com

# Third-party dependencies
https://github.com
https://stripe.com
```

Lines starting with `#` are comments. No code changes needed.

---

## API Reference

### Phase 5 — Core Endpoints

#### `GET /health`
Service liveness check. Used by load balancers and Kubernetes probes.

```bash
curl http://localhost:5000/health
```
```json
{
  "status": "healthy",
  "service": "website-health-monitor",
  "version": "2.0.0",
  "database_enabled": true,
  "total_checks_completed": 10,
  "monitor_interval_seconds": 60
}
```

#### `GET /websites`
Latest health check result for all monitored URLs.

```bash
curl http://localhost:5000/websites
curl http://localhost:5000/websites?status=DOWN
curl http://localhost:5000/websites?status=UP
```

#### `GET /metrics`
Aggregate statistics for dashboards and alerting.

```bash
curl http://localhost:5000/metrics
```
```json
{
  "total": 10, "up": 9, "down": 1,
  "availability_pct": 90.0,
  "avg_response_ms": 245,
  "performance_tiers": { "excellent": 2, "good": 3, "slow": 3, "critical": 1 }
}
```

#### `GET /logs`
Recent log entries from logs.txt.

```bash
curl http://localhost:5000/logs
curl http://localhost:5000/logs?limit=100
```

#### `POST /check`
Trigger an immediate on-demand health check.

```bash
curl -X POST http://localhost:5000/check
```

---

### Phase 7 — Database Analytics Endpoints

#### `GET /analytics`
Combined analytics — uptime, response times, incidents, failures.

```bash
curl http://localhost:5000/analytics
curl http://localhost:5000/analytics?hours=48
```

#### `GET /analytics/uptime`
Uptime percentage per website — the SLI metric.

```bash
curl http://localhost:5000/analytics/uptime
curl http://localhost:5000/analytics/uptime?hours=24
```
```json
[
  { "url": "https://google.com", "total_checks": 24,
    "uptime_pct": "100.00", "downtime_pct": "0.00" },
  { "url": "https://bad-site.com", "total_checks": 24,
    "uptime_pct": "75.00", "downtime_pct": "25.00" }
]
```

#### `GET /analytics/failures`
Downtime incidents and most frequently failing websites.

```bash
curl http://localhost:5000/analytics/failures
curl "http://localhost:5000/analytics/failures?hours=24&days=7"
```

#### `GET /history`
Full check history from MySQL.

```bash
curl http://localhost:5000/history
curl "http://localhost:5000/history?url=google.com&limit=50"
```

#### `GET /db/status`
MySQL connection status and table statistics.

```bash
curl http://localhost:5000/db/status
```
```json
{
  "db_enabled": true, "db_available": true,
  "total_websites": 10, "total_log_entries": 1440,
  "monitoring_since": "2026-06-17 05:38:05",
  "db_host": "mysql", "db_port": 3306
}
```

---

## Docker Commands Reference

```bash
# Build and start full stack (Flask + MySQL)
docker compose up --build

# Start in background
docker compose up -d --build

# View all logs
docker compose logs -f

# View only app logs
docker compose logs -f health-monitor

# View only MySQL logs
docker compose logs -f mysql

# Stop everything (keeps MySQL data)
docker compose down

# Stop everything and delete MySQL data
docker compose down -v

# Access MySQL directly
docker exec -it health-monitor-db mysql -u monitor_user -pmonitor_pass health_monitor

# Run analytics queries inside MySQL
docker exec -it health-monitor-db mysql -u monitor_user -pmonitor_pass \
  -e "SELECT url, COUNT(*) as checks FROM health_logs \
      JOIN websites ON websites.id=health_logs.website_id GROUP BY url;" \
  health_monitor
```

---

## SQL Analytics Reference

```sql
-- Uptime percentage per website
SELECT w.url,
  ROUND(SUM(hl.status = 'UP') / COUNT(*) * 100, 2) AS uptime_pct
FROM websites w
JOIN health_logs hl ON hl.website_id = w.id
WHERE hl.checked_at >= NOW() - INTERVAL 24 HOUR
GROUP BY w.id, w.url ORDER BY uptime_pct ASC;

-- Average response time per website
SELECT w.url, ROUND(AVG(hl.response_time_ms), 0) AS avg_ms
FROM websites w
JOIN health_logs hl ON hl.website_id = w.id
WHERE hl.status = 'UP'
GROUP BY w.id, w.url ORDER BY avg_ms ASC;

-- Most frequently failing websites
SELECT w.url, COUNT(*) AS failure_count
FROM health_logs hl
JOIN websites w ON w.id = hl.website_id
WHERE hl.status = 'DOWN'
  AND hl.checked_at >= NOW() - INTERVAL 7 DAY
GROUP BY w.id, w.url ORDER BY failure_count DESC LIMIT 10;
```

---

## Performance Tiers

| Tier | Response Time | Meaning |
|---|---|---|
| Excellent | < 200 ms | Meets Google Core Web Vitals TTFB target |
| Good | 200–500 ms | Acceptable for most web applications |
| Acceptable | 500 ms–1 s | Within typical SLO thresholds |
| Slow | 1–2 s | Users notice; warrants investigation |
| Critical | > 2 s | Significant user experience impact |

---

## Resume Points

> **Website Health Monitoring System v2.0** | Python · Flask · MySQL · Docker · Git

- Developed a production-style monitoring platform that continuously checks website availability and response latency across multiple endpoints, storing results in a normalised MySQL database.
- Designed a relational database schema with `websites` and `health_logs` tables, implementing proper foreign keys, composite indexes, and `INSERT IGNORE` upsert patterns.
- Built SQL analytics queries for SLI metrics — uptime percentage, average response times, downtime incident tracking, and failure frequency ranking.
- Implemented concurrent health checks using `ThreadPoolExecutor`, achieving ~20× speed improvement over sequential execution.
- Built a REST API with 11 Flask endpoints exposing real-time and historical monitoring data for dashboards and alerting systems.
- Containerised the full stack using Docker Compose — Flask application + MySQL 8.0 — with `depends_on: condition: service_healthy` to guarantee correct startup order.
- Applied Twelve-Factor App methodology — externalised all configuration via environment variables using `python-dotenv` for portable deployment.
- Implemented graceful database degradation — system continues operating with file-based logging when `DB_ENABLED=false`, ensuring zero breaking changes.

---

## Interview Topics Covered

| Topic | Where demonstrated |
|---|---|
| Normalised DB schema | schema.sql — websites + health_logs with FK |
| SQL aggregations | GROUP BY, AVG(), SUM(), COUNT() in queries.sql |
| SLI / SLO / SLA | /analytics/uptime endpoint |
| Uptime percentage | SQL: SUM(status='UP') / COUNT(*) × 100 |
| INSERT IGNORE pattern | get_or_create_website() in database.py |
| Connection management | Context manager (_cursor) in database.py |
| Environment variables | python-dotenv + .env.example |
| Docker service ordering | depends_on + healthcheck in docker-compose.yml |
| DB graceful degradation | DB_ENABLED flag pattern |
| Thread safety | threading.Lock() for shared state |
| REST API design | 11 endpoints with query parameters |
| Containerisation | Multi-service Docker Compose |

---

## Future Enhancements

- [ ] **Email/Slack alerts** — webhook notifications on downtime
- [ ] **Prometheus metrics** — `/metrics` in Prometheus format for Grafana
- [ ] **Grafana dashboard** — pre-built dashboard consuming analytics endpoints
- [ ] **TimescaleDB** — replace MySQL with purpose-built time-series database
- [ ] **Kubernetes deployment** — Helm chart with ConfigMap for websites.txt
- [ ] **GitHub Actions CI/CD** — automated test + Docker build + push pipeline
- [ ] **API authentication** — JWT or API key middleware for Flask endpoints
- [ ] **Log rotation** — archive logs.txt when size exceeds threshold

---

## Author

**Vaibhav Shukla** | [github.com/VaibhavShukla29](https://github.com/VaibhavShukla29)

Built as a DevOps/CloudOps portfolio project demonstrating monitoring, REST APIs,
relational databases, SQL analytics, concurrency, and full-stack Docker deployment.
