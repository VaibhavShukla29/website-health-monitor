"""
database.py  —  MySQL Database Layer  (Phase 7)
================================================
Handles all MySQL operations for the Website Health Monitoring System.

Responsibilities:
    - Open and close database connections
    - Create tables automatically on startup
    - Save every health check result to MySQL
    - Provide analytics query functions for the Flask API

Design principles:
    - DB_ENABLED flag  : if False, every function returns safely without error
    - Fail gracefully  : DB failure never crashes the monitoring loop
    - Pure SQL         : no ORM — SQL is written directly so you can learn it
    - One connection per operation : simple and safe for this use case

Tables managed:
    websites     — master list of URLs (one row per URL)
    health_logs  — every check result (one row per check per URL)

Industry context:
    Production monitoring systems store results in databases like:
        PostgreSQL   — most popular open-source relational DB
        MySQL        — widely used in web applications (LAMP stack)
        InfluxDB     — purpose-built time-series database
        TimescaleDB  — PostgreSQL extension for time-series data
    
    The SQL patterns here (aggregations, time-range queries, GROUP BY)
    are the same patterns used in Grafana data sources and SRE dashboards.
"""

import os
import logging
from contextlib import contextmanager
from datetime import datetime

from dotenv import load_dotenv

# Load .env file into environment variables
# This runs before reading os.getenv() calls below
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────────────────────────────────────

_logger = logging.getLogger("db_layer")
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | DB | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _logger.addHandler(_handler)
    _logger.propagate = False


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# All values come from the .env file or environment variables.
# Defaults are safe for local development.
# ─────────────────────────────────────────────────────────────────────────────

DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER",     "monitor_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "monitor_pass")
DB_NAME     = os.getenv("DB_NAME",     "health_monitor")

# Master switch: set DB_ENABLED=true in .env to activate MySQL storage.
# When false, all functions return immediately without touching the database.
# This makes MySQL completely optional — the system works without it.
DB_ENABLED  = os.getenv("DB_ENABLED",  "false").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT PyMySQL
# Wrapped in try/except so the app starts even if PyMySQL is not installed.
# ─────────────────────────────────────────────────────────────────────────────

try:
    import pymysql
    import pymysql.cursors
    _PYMYSQL_AVAILABLE = True
except ImportError:
    _PYMYSQL_AVAILABLE = False
    _logger.warning(
        "PyMySQL not installed. Run: pip install PyMySQL==1.1.1"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _get_connection():
    """
    Open and return a new MySQL connection.

    Why PyMySQL?
        Pure Python — no C extensions or system libraries required.
        Works identically on Windows, Mac, Linux, and inside Docker.

    Why DictCursor?
        Returns rows as dicts ({"url": "google.com", "status": "UP"})
        instead of tuples ((\"google.com\", \"UP\")), making results
        directly usable as JSON responses in Flask.

    Why autocommit=True?
        Each INSERT/UPDATE commits immediately without needing
        conn.commit() calls. Safe for our INSERT-heavy workload.
    """
    if not _PYMYSQL_AVAILABLE:
        raise RuntimeError(
            "PyMySQL not installed. Run: pip install PyMySQL==1.1.1"
        )

    return pymysql.connect(
        host            = DB_HOST,
        port            = DB_PORT,
        user            = DB_USER,
        password        = DB_PASSWORD,
        database        = DB_NAME,
        charset         = "utf8mb4",
        cursorclass     = pymysql.cursors.DictCursor,
        autocommit      = True,
        connect_timeout = 10,
    )


@contextmanager
def _cursor():
    """
    Context manager: opens a connection, yields a cursor, always closes.

    Using 'with _cursor() as cur:' guarantees the connection is closed
    even if an exception occurs inside the block.

    Example:
        with _cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM health_logs")
            row = cur.fetchone()
            print(row["total"])
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# TABLE SCHEMA
# Written as Python string so we don't need an external .sql file at runtime.
# The same schema is in schema.sql for reference and manual setup.
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_WEBSITES_TABLE = """
CREATE TABLE IF NOT EXISTS websites (
    id          INT           NOT NULL AUTO_INCREMENT,
    url         VARCHAR(500)  NOT NULL,
    name        VARCHAR(255)      NULL,
    is_active   TINYINT(1)    NOT NULL DEFAULT 1,
    created_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                       ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE  KEY uq_url (url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CREATE_HEALTH_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS health_logs (
    id               BIGINT        NOT NULL AUTO_INCREMENT,
    website_id       INT           NOT NULL,
    status           VARCHAR(10)   NOT NULL,
    status_code      SMALLINT          NULL,
    response_time_ms INT               NULL,
    performance      VARCHAR(20)       NULL,
    error_message    VARCHAR(500)      NULL,
    checked_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_website
        FOREIGN KEY (website_id)
        REFERENCES websites (id)
        ON DELETE CASCADE,
    INDEX idx_website_id      (website_id),
    INDEX idx_checked_at      (checked_at),
    INDEX idx_status          (status),
    INDEX idx_website_checked (website_id, checked_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


# ─────────────────────────────────────────────────────────────────────────────
# INITIALISATION
# ─────────────────────────────────────────────────────────────────────────────

def init_database() -> bool:
    """
    Create both tables if they do not already exist.
    Called once when the application starts (in app.py and monitor.py).

    CREATE TABLE IF NOT EXISTS is idempotent — safe to call every startup.
    It will never error or erase existing data.

    Returns:
        True  — tables ready
        False — DB disabled or error occurred
    """
    if not DB_ENABLED:
        _logger.info("DB_ENABLED=false — skipping database initialisation.")
        return False

    try:
        with _cursor() as cur:
            cur.execute(_CREATE_WEBSITES_TABLE)
            cur.execute(_CREATE_HEALTH_LOGS_TABLE)

        _logger.info(
            f"Database initialised — connected to {DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
        return True

    except Exception as exc:
        _logger.error(f"Database initialisation failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def is_db_available() -> bool:
    """
    Ping MySQL to check if the server is reachable.
    Used by the GET /db/status API endpoint.

    Returns True if connected, False if unreachable or disabled.
    """
    if not DB_ENABLED or not _PYMYSQL_AVAILABLE:
        return False
    try:
        with _cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# WEBSITE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_website(url: str) -> int | None:
    """
    Return the database ID for a URL, creating the row if it does not exist.

    Pattern used: INSERT IGNORE + SELECT
        INSERT IGNORE inserts a new row if the URL is new.
        If the URL already exists (UNIQUE KEY violation), IGNORE skips silently.
        SELECT then fetches the ID whether it was just inserted or pre-existing.

    This is called before every INSERT into health_logs because health_logs
    requires a valid website_id foreign key.

    Args:
        url (str): Full URL e.g. "https://google.com"

    Returns:
        int  — website ID on success
        None — on failure
    """
    try:
        with _cursor() as cur:
            # Insert if not exists (silently skip on duplicate)
            cur.execute(
                "INSERT IGNORE INTO websites (url) VALUES (%s)",
                (url,)
            )
            # Fetch ID (works whether row was just created or already existed)
            cur.execute(
                "SELECT id FROM websites WHERE url = %s",
                (url,)
            )
            row = cur.fetchone()
            return row["id"] if row else None

    except Exception as exc:
        _logger.error(f"get_or_create_website failed for {url}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH LOG WRITE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def log_health_check(result: dict) -> bool:
    """
    Save a single health check result to the health_logs table.

    Called after every check_website() call. If the DB write fails,
    the monitoring loop is NOT affected — the error is logged and skipped.

    Args:
        result (dict): The dict returned by monitor.check_website()
                       Keys: url, status, status_code, response_time_ms,
                             performance, error, timestamp

    Returns:
        True  — successfully saved
        False — DB disabled, unavailable, or error
    """
    if not DB_ENABLED:
        return False

    try:
        website_id = get_or_create_website(result["url"])
        if website_id is None:
            return False

        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO health_logs
                    (website_id, status, status_code,
                     response_time_ms, performance,
                     error_message, checked_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    website_id,
                    result.get("status"),
                    result.get("status_code"),
                    result.get("response_time_ms"),
                    result.get("performance"),
                    result.get("error"),
                    result.get("timestamp"),
                )
            )
        return True

    except Exception as exc:
        _logger.error(f"log_health_check failed for {result.get('url')}: {exc}")
        return False


def log_health_checks_batch(results: list) -> int:
    """
    Save a full monitoring cycle (multiple results) to the database.
    Called at the end of each check cycle in monitor.py and app.py.

    Args:
        results (list): List of result dicts from check_website()

    Returns:
        int — number of results successfully saved
    """
    if not DB_ENABLED:
        return 0

    saved = 0
    for result in results:
        if log_health_check(result):
            saved += 1

    if saved > 0:
        _logger.info(f"Saved {saved}/{len(results)} results to MySQL")

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS QUERY FUNCTIONS
# Each function maps to one SQL query from queries.sql
# ─────────────────────────────────────────────────────────────────────────────

def get_avg_response_times(hours: int = 24) -> list:
    """
    Query 1 — Average response time per website.

    Returns average, minimum, and maximum response times for each website
    over the last `hours` hours.

    SQL concept used: GROUP BY + AVG() + MIN() + MAX() aggregation.

    Args:
        hours (int): Time window in hours (default: 24)

    Returns:
        list of dicts: [{url, avg_response_ms, min_response_ms,
                         max_response_ms, total_checks, avg_performance}, ...]
    """
    if not DB_ENABLED:
        return []

    try:
        with _cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.url,
                    COUNT(*)                             AS total_checks,
                    ROUND(AVG(hl.response_time_ms), 0)  AS avg_response_ms,
                    MIN(hl.response_time_ms)             AS min_response_ms,
                    MAX(hl.response_time_ms)             AS max_response_ms,
                    CASE
                        WHEN AVG(hl.response_time_ms) < 200  THEN 'Excellent'
                        WHEN AVG(hl.response_time_ms) < 500  THEN 'Good'
                        WHEN AVG(hl.response_time_ms) < 1000 THEN 'Acceptable'
                        WHEN AVG(hl.response_time_ms) < 2000 THEN 'Slow'
                        ELSE 'Critical'
                    END AS avg_performance
                FROM websites w
                JOIN health_logs hl
                    ON  hl.website_id = w.id
                    AND hl.status     = 'UP'
                    AND hl.checked_at >= NOW() - INTERVAL %s HOUR
                GROUP BY w.id, w.url
                ORDER BY avg_response_ms ASC
                """,
                (hours,)
            )
            return cur.fetchall()

    except Exception as exc:
        _logger.error(f"get_avg_response_times failed: {exc}")
        return []


def get_uptime_stats(hours: int = 24) -> list:
    """
    Query 2 — Uptime percentage per website (the SLI metric).

    Calculates the percentage of checks that returned UP vs DOWN
    for each website over the last `hours` hours.

    SQL concept used: SUM(condition) to count rows matching a condition.
    SUM(hl.status = 'UP') counts how many rows have status='UP'.

    Args:
        hours (int): Time window in hours (default: 24)

    Returns:
        list of dicts: [{url, total_checks, up_count, down_count,
                         uptime_pct, downtime_pct}, ...]
    """
    if not DB_ENABLED:
        return []

    try:
        with _cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.url,
                    COUNT(*)                                           AS total_checks,
                    SUM(hl.status = 'UP')                             AS up_count,
                    SUM(hl.status = 'DOWN')                           AS down_count,
                    ROUND(SUM(hl.status = 'UP') / COUNT(*) * 100, 2) AS uptime_pct,
                    ROUND(SUM(hl.status = 'DOWN') / COUNT(*) * 100, 2) AS downtime_pct,
                    MAX(hl.checked_at)                                AS last_checked
                FROM websites w
                JOIN health_logs hl
                    ON  hl.website_id = w.id
                    AND hl.checked_at >= NOW() - INTERVAL %s HOUR
                GROUP BY w.id, w.url
                ORDER BY uptime_pct ASC
                """,
                (hours,)
            )
            return cur.fetchall()

    except Exception as exc:
        _logger.error(f"get_uptime_stats failed: {exc}")
        return []


def get_downtime_incidents(hours: int = 24, limit: int = 50) -> list:
    """
    Query 3 — Downtime incidents (every DOWN event).

    Returns every DOWN check result within the time window,
    most recent first. Used for incident investigation.

    Args:
        hours (int): Time window in hours (default: 24)
        limit (int): Maximum rows to return (default: 50)

    Returns:
        list of dicts: [{url, error_message, checked_at}, ...]
    """
    if not DB_ENABLED:
        return []

    try:
        with _cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.url,
                    hl.error_message,
                    hl.checked_at
                FROM health_logs hl
                JOIN websites w ON w.id = hl.website_id
                WHERE
                    hl.status     = 'DOWN'
                    AND hl.checked_at >= NOW() - INTERVAL %s HOUR
                ORDER BY hl.checked_at DESC
                LIMIT %s
                """,
                (hours, limit)
            )
            return cur.fetchall()

    except Exception as exc:
        _logger.error(f"get_downtime_incidents failed: {exc}")
        return []


def get_most_failing(days: int = 7, limit: int = 10) -> list:
    """
    Query 4 — Most frequently failing websites.

    Counts total DOWN events per website over the last `days` days.
    Websites at the top of this list need attention.

    SQL concept used: GROUP BY + COUNT + ORDER BY DESC + LIMIT

    Args:
        days  (int): Time window in days (default: 7)
        limit (int): Number of websites to return (default: 10)

    Returns:
        list of dicts: [{url, failure_count, last_failure, error_types}, ...]
    """
    if not DB_ENABLED:
        return []

    try:
        with _cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.url,
                    COUNT(*)         AS failure_count,
                    MAX(hl.checked_at) AS last_failure,
                    GROUP_CONCAT(
                        DISTINCT hl.error_message
                        ORDER BY hl.error_message
                        SEPARATOR ' | '
                    )                AS error_types
                FROM health_logs hl
                JOIN websites w ON w.id = hl.website_id
                WHERE
                    hl.status     = 'DOWN'
                    AND hl.checked_at >= NOW() - INTERVAL %s DAY
                GROUP BY w.id, w.url
                ORDER BY failure_count DESC
                LIMIT %s
                """,
                (days, limit)
            )
            return cur.fetchall()

    except Exception as exc:
        _logger.error(f"get_most_failing failed: {exc}")
        return []


def get_check_history(url: str = None, limit: int = 100) -> list:
    """
    Query 5 — Recent check history.

    Returns the most recent `limit` check results.
    If `url` is provided, returns history for that specific website only.
    If `url` is None, returns history for all websites.

    Args:
        url   (str): Filter to one website (optional)
        limit (int): Max rows to return (default: 100)

    Returns:
        list of dicts: [{url, status, status_code, response_time_ms,
                         performance, error_message, checked_at}, ...]
    """
    if not DB_ENABLED:
        return []

    try:
        with _cursor() as cur:
            if url:
                cur.execute(
                    """
                    SELECT
                        w.url,
                        hl.status,
                        hl.status_code,
                        hl.response_time_ms,
                        hl.performance,
                        hl.error_message,
                        hl.checked_at
                    FROM health_logs hl
                    JOIN websites w ON w.id = hl.website_id
                    WHERE w.url LIKE %s
                    ORDER BY hl.checked_at DESC
                    LIMIT %s
                    """,
                    (f"%{url}%", limit)
                )
            else:
                cur.execute(
                    """
                    SELECT
                        w.url,
                        hl.status,
                        hl.status_code,
                        hl.response_time_ms,
                        hl.performance,
                        hl.error_message,
                        hl.checked_at
                    FROM health_logs hl
                    JOIN websites w ON w.id = hl.website_id
                    ORDER BY hl.checked_at DESC
                    LIMIT %s
                    """,
                    (limit,)
                )
            return cur.fetchall()

    except Exception as exc:
        _logger.error(f"get_check_history failed: {exc}")
        return []


def get_db_info() -> dict:
    """
    Query 6 — Database statistics and metadata.

    Returns counts, storage info, and monitoring coverage dates.
    Used by the GET /db/status endpoint.

    Returns:
        dict with database statistics, or empty dict if unavailable.
    """
    if not DB_ENABLED:
        return {
            "db_enabled":  False,
            "db_available": False,
            "message":     "Set DB_ENABLED=true in .env to activate MySQL",
        }

    if not is_db_available():
        return {
            "db_enabled":  True,
            "db_available": False,
            "message":     "MySQL server is not reachable",
            "host":        DB_HOST,
            "port":        DB_PORT,
        }

    try:
        with _cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM websites)                     AS total_websites,
                    (SELECT COUNT(*) FROM websites WHERE is_active = 1) AS active_websites,
                    (SELECT COUNT(*) FROM health_logs)                  AS total_log_entries,
                    (SELECT COUNT(*) FROM health_logs
                     WHERE checked_at >= NOW() - INTERVAL 24 HOUR)     AS entries_last_24h,
                    (SELECT MIN(checked_at) FROM health_logs)           AS monitoring_since,
                    (SELECT MAX(checked_at) FROM health_logs)           AS last_check
                """
            )
            stats = cur.fetchone()

        stats["db_enabled"]   = True
        stats["db_available"] = True
        stats["db_host"]      = DB_HOST
        stats["db_port"]      = DB_PORT
        stats["db_name"]      = DB_NAME

        # Convert datetime objects to strings for JSON serialisation
        for key in ("monitoring_since", "last_check"):
            if stats.get(key) and hasattr(stats[key], "isoformat"):
                stats[key] = stats[key].strftime("%Y-%m-%d %H:%M:%S")

        return stats

    except Exception as exc:
        _logger.error(f"get_db_info failed: {exc}")
        return {"db_enabled": True, "db_available": False, "error": str(exc)}


def get_all_analytics(hours: int = 24) -> dict:
    """
    Combined analytics — calls all query functions and merges results.
    Used by the GET /analytics endpoint to return everything in one call.

    Args:
        hours (int): Time window for all queries (default: 24)

    Returns:
        dict with all analytics sections.
    """
    return {
        "time_window_hours":  hours,
        "uptime_stats":       get_uptime_stats(hours),
        "avg_response_times": get_avg_response_times(hours),
        "downtime_incidents": get_downtime_incidents(hours),
        "most_failing":       get_most_failing(days=max(1, hours // 24) * 7),
    }
