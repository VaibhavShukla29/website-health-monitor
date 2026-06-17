-- Analytics queries reference for Website Health Monitoring System
USE health_monitor;

-- 1. Uptime percentage per website
SELECT w.url,
  ROUND(SUM(hl.status = 'UP') / COUNT(*) * 100, 2) AS uptime_pct
FROM websites w
JOIN health_logs hl ON hl.website_id = w.id
GROUP BY w.id, w.url ORDER BY uptime_pct ASC;

-- 2. Average response time per website
SELECT w.url, ROUND(AVG(hl.response_time_ms), 0) AS avg_response_ms
FROM websites w
JOIN health_logs hl ON hl.website_id = w.id
WHERE hl.status = 'UP'
GROUP BY w.id, w.url ORDER BY avg_response_ms ASC;

-- 3. Most frequently failing websites
SELECT w.url, COUNT(*) AS failure_count
FROM health_logs hl
JOIN websites w ON w.id = hl.website_id
WHERE hl.status = 'DOWN'
GROUP BY w.id, w.url ORDER BY failure_count DESC LIMIT 10;

-- 4. Downtime incidents last 24 hours
SELECT w.url, hl.error_message, hl.checked_at
FROM health_logs hl
JOIN websites w ON w.id = hl.website_id
WHERE hl.status = 'DOWN'
  AND hl.checked_at >= NOW() - INTERVAL 24 HOUR
ORDER BY hl.checked_at DESC;
