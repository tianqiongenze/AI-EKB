CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skills (
    skill_name VARCHAR(191) NOT NULL,
    version VARCHAR(64) NOT NULL,
    owner VARCHAR(191) NOT NULL,
    risk_level VARCHAR(32) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    allowed_tools_json JSON NOT NULL,
    allowed_domains_json JSON NOT NULL,
    residency_scope_json JSON NOT NULL,
    input_schema_json JSON NOT NULL,
    output_schema_json JSON NOT NULL,
    changelog TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (skill_name, version)
);

CREATE TABLE IF NOT EXISTS audits (
    id BIGINT NOT NULL AUTO_INCREMENT,
    tenant_id VARCHAR(191) NOT NULL,
    region_id VARCHAR(64) NOT NULL,
    plant_id VARCHAR(128) NOT NULL,
    user_or_agent_id VARCHAR(191) NOT NULL,
    skill_name VARCHAR(191) NOT NULL,
    skill_version VARCHAR(64) NOT NULL,
    tool_name VARCHAR(191) NOT NULL,
    decision_reason VARCHAR(128) NOT NULL,
    accepted TINYINT(1) NOT NULL,
    payload_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_audits_tenant_created (tenant_id, created_at)
);

CREATE TABLE IF NOT EXISTS harness_runs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    tenant_id VARCHAR(191) NOT NULL,
    skill_name VARCHAR(191) NOT NULL,
    skill_version VARCHAR(64) NOT NULL,
    quality_score DOUBLE NOT NULL,
    safety_score DOUBLE NOT NULL,
    regression_score DOUBLE NOT NULL,
    latency_ms INT NOT NULL,
    accepted TINYINT(1) NOT NULL,
    reasons_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_harness_tenant_created (tenant_id, created_at)
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    event_type VARCHAR(191) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    retries INT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL,
    claimed_by VARCHAR(128) NOT NULL DEFAULT '',
    claimed_at TIMESTAMP NULL,
    next_retry_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP NULL,
    PRIMARY KEY (id),
    KEY idx_outbox_status_id (status, id),
    KEY idx_outbox_claimed (status, claimed_by, claimed_at),
    KEY idx_outbox_retry (status, next_retry_at, id)
);

CREATE TABLE IF NOT EXISTS business_capabilities (
    id BIGINT NOT NULL AUTO_INCREMENT,
    domain VARCHAR(64) NOT NULL,
    capability_type VARCHAR(128) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    owner VARCHAR(191) NOT NULL,
    maturity VARCHAR(32) NOT NULL,
    tags_json JSON NOT NULL,
    metadata_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_domain_capability (domain, capability_type, title),
    KEY idx_domain_maturity (domain, maturity)
);
