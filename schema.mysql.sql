CREATE TABLE IF NOT EXISTS users (
    user_key VARCHAR(64) PRIMARY KEY,
    username VARCHAR(20) NOT NULL UNIQUE,
    salt CHAR(32) NOT NULL,
    password_hash CHAR(64) NOT NULL,
    password_iterations INT NOT NULL,
    created_at BIGINT NOT NULL,
    nickname VARCHAR(20) NOT NULL,
    bio VARCHAR(160) NOT NULL,
    privacy_version VARCHAR(32) NULL,
    privacy_accepted_at BIGINT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'user',
    muted_until BIGINT NULL,
    banned_until BIGINT NULL,
    ban_reason VARCHAR(255) NOT NULL DEFAULT '',
    friends_json LONGTEXT NOT NULL,
    friend_requests_json LONGTEXT NOT NULL,
    blocked_users_json LONGTEXT NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reports (
    report_id CHAR(32) PRIMARY KEY,
    report_type VARCHAR(20) NOT NULL,
    reporter_key VARCHAR(64) NOT NULL,
    target_key VARCHAR(64) NULL,
    target_username VARCHAR(20) NOT NULL DEFAULT '',
    reason VARCHAR(500) NOT NULL,
    message_text VARCHAR(200) NOT NULL DEFAULT '',
    message_id VARCHAR(80) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    action VARCHAR(32) NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    metadata_json LONGTEXT NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
