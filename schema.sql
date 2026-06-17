CREATE DATABASE IF NOT EXISTS health_monitor CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE health_monitor;

CREATE TABLE IF NOT EXISTS websites (
    id         INT           NOT NULL AUTO_INCREMENT,
    url        VARCHAR(500)  NOT NULL,
    name       VARCHAR(255)      NULL,
    is_active  TINYINT(1)    NOT NULL DEFAULT 1,
    created_at TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_url (url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS health_logs (
    id               BIGINT       NOT NULL AUTO_INCREMENT,
    website_id       INT          NOT NULL,
    status           VARCHAR(10)  NOT NULL,
    status_code      SMALLINT         NULL,
    response_time_ms INT              NULL,
    performance      VARCHAR(20)      NULL,
    error_message    VARCHAR(500)     NULL,
    checked_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_website FOREIGN KEY (website_id) REFERENCES websites (id) ON DELETE CASCADE,
    INDEX idx_website_id (website_id),
    INDEX idx_checked_at (checked_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
