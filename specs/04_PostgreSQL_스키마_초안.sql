-- Micro Asset Marketplace Database Schema — draft v1.0 (2026-11-12)
-- Purpose: DESIGN REFERENCE, not a tested production migration.
-- Requires PostgreSQL >= 14 and pgcrypto for gen_random_uuid() where needed.
-- Apply through Alembic migrations AFTER reviewing actual ORM/model consistency.
-- SECURITY: never run arbitrary seller code inside the DB or the web server.
-- SECURITY: every row is subject to server-side RBAC and ownership authorization.
-- DEMO: all transaction records are explicitly demo-only in MVP.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(320) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'USER'
      CHECK (role IN ('USER','ADMIN')),
    email_verified_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email));

CREATE TABLE listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seller_id UUID NOT NULL REFERENCES users(id),
    title VARCHAR(120) NOT NULL CHECK (char_length(trim(title)) >= 2),
    description TEXT NOT NULL CHECK (char_length(trim(description)) >= 30),
    category VARCHAR(40) NOT NULL CHECK (category IN
       ('web_app','saas','desktop_tool','ai_agent','mobile_app','game','module','content_asset','revenue_site')),
    lifecycle_status VARCHAR(40) NOT NULL CHECK (lifecycle_status IN
       ('UNLAUNCHED','IN_DEVELOPMENT','DISCONTINUED','FAILED_COMMERCIALIZATION',
        'OPERATING_NO_REVENUE','OPERATING_REVENUE','ASSET_ONLY')),
    sale_rights_type VARCHAR(60) NOT NULL CHECK (sale_rights_type IN
       ('FULL_IP_ASSIGNMENT','EXCLUSIVE_LICENSE','NON_EXCLUSIVE_LICENSE',
        'ASSET_TRANSFER_ONLY','BUSINESS_TRANSFER_REVIEW_REQUIRED')),
    inventory_mode VARCHAR(20) NOT NULL DEFAULT 'ONE_TIME'
      CHECK (inventory_mode IN ('ONE_TIME','REPEAT_LICENSE')),
    price_krw BIGINT NOT NULL CHECK (price_krw > 0),
    tech_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
    included_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
    excluded_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
    known_defects JSONB NOT NULL DEFAULT '[]'::jsonb,
    monthly_cost_estimate_krw BIGINT CHECK (monthly_cost_estimate_krw >= 0),
    handover_days_estimate INTEGER CHECK (handover_days_estimate >= 0),
    seller_support_days INTEGER CHECK (seller_support_days >= 0),
    has_revenue BOOLEAN NOT NULL DEFAULT FALSE,
    revenue_krw_claimed BIGINT CHECK (revenue_krw_claimed >= 0),
    revenue_claim_verification VARCHAR(40) NOT NULL DEFAULT 'NOT_PROVIDED'
      CHECK (revenue_claim_verification IN ('NOT_PROVIDED','SELLER_CLAIMED_UNVERIFIED','DOCUMENT_REVIEWED')),
    verification_status VARCHAR(32) NOT NULL DEFAULT 'UNVERIFIED'
      CHECK (verification_status IN ('UNVERIFIED','STATIC_CHECKED','EXECUTION_CHECKED','PARTIAL')),
    status VARCHAR(24) NOT NULL DEFAULT 'DRAFT'
      CHECK (status IN ('DRAFT','PENDING_REVIEW','ACTIVE','PAUSED','RESERVED','CLOSED','REMOVED')),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    seller_ownership_attested_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (inventory_mode <> 'REPEAT_LICENSE' OR sale_rights_type = 'NON_EXCLUSIVE_LICENSE')
);
CREATE INDEX ix_listings_public_catalog
    ON listings (status, is_demo, category, price_krw, created_at DESC);
CREATE INDEX ix_listings_seller_status ON listings (seller_id, status);

CREATE TABLE listing_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    asset_type VARCHAR(24) NOT NULL CHECK (asset_type IN
       ('SOURCE_ARCHIVE','DOCUMENT','SCREENSHOT','DEMO_VIDEO','LICENSE','MANIFEST')),
    file_name VARCHAR(255) NOT NULL,
    private_object_key TEXT NOT NULL UNIQUE,
    content_type VARCHAR(160) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    checksum_sha256 CHAR(64) NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    visibility VARCHAR(40) NOT NULL DEFAULT 'PRIVATE_SELLER'
      CHECK (visibility IN ('PUBLIC_PREVIEW','PRIVATE_SELLER','SHARED_WITH_APPROVED_BUYER')),
    upload_status VARCHAR(24) NOT NULL DEFAULT 'PENDING'
      CHECK (upload_status IN ('PENDING','QUARANTINED','SCANNED','REJECTED')),
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_listing_assets_listing ON listing_assets(listing_id);

CREATE TABLE buyer_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    min_budget_krw BIGINT NOT NULL DEFAULT 0 CHECK (min_budget_krw >= 0),
    max_budget_krw BIGINT NOT NULL DEFAULT 1000000 CHECK (max_budget_krw >= min_budget_krw),
    skill_level VARCHAR(20) NOT NULL DEFAULT 'BASIC'
      CHECK (skill_level IN ('NONE','BASIC','INTERMEDIATE','ADVANCED')),
    objectives JSONB NOT NULL DEFAULT '[]'::jsonb,
    preferred_tech_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
    max_monthly_cost_krw BIGINT CHECK (max_monthly_cost_krw >= 0),
    risk_tolerance VARCHAR(12) NOT NULL DEFAULT 'MEDIUM'
      CHECK (risk_tolerance IN ('LOW','MEDIUM','HIGH')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE favorites (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(user_id, listing_id)
);

CREATE TABLE offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES listings(id),
    buyer_id UUID NOT NULL REFERENCES users(id),
    seller_id UUID NOT NULL REFERENCES users(id),
    parent_offer_id UUID REFERENCES offers(id),
    proposed_by UUID NOT NULL REFERENCES users(id),
    offered_price_krw BIGINT NOT NULL CHECK (offered_price_krw > 0),
    terms_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
      CHECK (status IN ('PENDING','ACCEPTED','DECLINED','WITHDRAWN','EXPIRED','COUNTERED')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    is_demo BOOLEAN NOT NULL DEFAULT TRUE CHECK (is_demo = TRUE),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (buyer_id <> seller_id),
    CHECK (proposed_by IN (buyer_id, seller_id))
);
CREATE INDEX ix_offers_listing_status ON offers (listing_id, status, created_at DESC);
CREATE INDEX ix_offers_buyer ON offers (buyer_id, created_at DESC);
CREATE INDEX ix_offers_seller ON offers (seller_id, created_at DESC);

CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES listings(id),
    accepted_offer_id UUID NOT NULL UNIQUE REFERENCES offers(id),
    buyer_id UUID NOT NULL REFERENCES users(id),
    seller_id UUID NOT NULL REFERENCES users(id),
    exclusive_guard_listing_id UUID REFERENCES listings(id),
    status VARCHAR(32) NOT NULL DEFAULT 'AWAITING_HANDOVER'
      CHECK (status IN ('AWAITING_HANDOVER','HANDOVER_IN_PROGRESS','HANDOVER_REVIEW',
                       'DEMO_COMPLETED','DISPUTED','CANCELLED')),
    is_demo BOOLEAN NOT NULL DEFAULT TRUE CHECK (is_demo = TRUE),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (buyer_id <> seller_id),
    CHECK (exclusive_guard_listing_id IS NULL OR exclusive_guard_listing_id = listing_id)
);
-- For ONE_TIME assets application sets exclusive_guard_listing_id=listing_id inside
-- a locked database transaction. REPEAT_LICENSE uses NULL for repeatable sales.
CREATE UNIQUE INDEX ux_transactions_exclusive_open
    ON transactions(exclusive_guard_listing_id)
    WHERE exclusive_guard_listing_id IS NOT NULL AND status <> 'CANCELLED';
CREATE INDEX ix_transactions_buyer ON transactions (buyer_id, created_at DESC);
CREATE INDEX ix_transactions_seller ON transactions (seller_id, created_at DESC);

CREATE TABLE handover_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    check_key VARCHAR(100) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    seller_submitted BOOLEAN NOT NULL DEFAULT FALSE,
    agent_checked BOOLEAN NOT NULL DEFAULT FALSE,
    buyer_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    result VARCHAR(24) NOT NULL DEFAULT 'NOT_TESTED'
      CHECK (result IN ('SELLER_SUBMITTED','AGENT_CHECKED','BUYER_CONFIRMED','NEEDS_FIX','NOT_TESTED')),
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    remarks TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(transaction_id, check_key)
);
CREATE INDEX ix_handover_transaction ON handover_checks(transaction_id);

CREATE TABLE handover_check_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    handover_check_id UUID NOT NULL REFERENCES handover_checks(id),
    actor_user_id UUID REFERENCES users(id),
    actor_kind VARCHAR(18) NOT NULL CHECK (actor_kind IN ('SELLER','BUYER','AGENT','ADMIN')),
    old_result VARCHAR(24),
    new_result VARCHAR(24) NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE inspection_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES listings(id),
    report_type VARCHAR(32) NOT NULL CHECK (report_type IN
       ('STATIC','EXECUTION','HANDOVER','LEGAL_CHECKLIST')),
    verdict VARCHAR(24) NOT NULL CHECK (verdict IN
       ('NOT_TESTED','UNVERIFIED','PASS','PARTIAL','FAIL')),
    reviewer_kind VARCHAR(24) NOT NULL CHECK (reviewer_kind IN
       ('AI_AGENT','HUMAN','THIRD_PARTY')),
    submitted_by_user_id UUID REFERENCES users(id),
    agent_job_id UUID,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_version_sha256 CHAR(64),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_inspection_listing_created ON inspection_reports(listing_id, created_at DESC);

CREATE TABLE agent_action_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    requesting_agent_id VARCHAR(128) NOT NULL,
    action_type VARCHAR(40) NOT NULL CHECK (action_type IN
       ('SUBMIT_OFFER','COUNTER_OFFER','RECORD_HANDOVER_CHECK','REQUEST_SELLER_FIX')),
    resource_id UUID NOT NULL,
    proposed_payload JSONB NOT NULL,
    payload_sha256 CHAR(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING_APPROVAL'
      CHECK (status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','EXECUTED','EXPIRED')),
    expires_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    result_resource_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_agent_action_user_status ON agent_action_requests(user_id, status, expires_at);

CREATE TABLE service_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_user_id UUID NOT NULL REFERENCES users(id),
    client_id VARCHAR(128) NOT NULL,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    granted_listing_id UUID REFERENCES listings(id),
    granted_transaction_id UUID REFERENCES transactions(id),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_service_grants_principal ON service_grants(principal_user_id, expires_at);

CREATE TABLE moderation_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL REFERENCES listings(id),
    reported_by UUID REFERENCES users(id),
    reason_code VARCHAR(40) NOT NULL,
    description TEXT,
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN'
      CHECK(status IN ('OPEN','IN_REVIEW','ACTIONED','DISMISSED')),
    resolved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID REFERENCES users(id),
    actor_type VARCHAR(16) NOT NULL CHECK (actor_type IN ('USER','AGENT','ADMIN','SYSTEM')),
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(48) NOT NULL,
    resource_id UUID,
    old_state JSONB,
    new_state JSONB,
    request_id VARCHAR(128),
    is_demo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_audit_resource ON audit_events(resource_type,resource_id,created_at DESC);
CREATE INDEX ix_audit_actor ON audit_events(actor_user_id,created_at DESC);

-- Required APPLICATION invariants, not automatically guaranteed by these DDL constraints:
-- 1. A seller can create/update only their own listing; buyer and seller parties are checked.
-- 2. Counter offers must use same listing, buyer, seller and alternate proposed_by.
-- 3. Offer accept/decline should use SELECT ... FOR UPDATE and expected_version.
-- 4. accepted_offer_id must refer to the same listing, buyer, seller as transaction.
-- 5. ONE_TIME transactions must set exclusive_guard_listing_id under row lock.
-- 6. REPEAT_LICENSE transaction requires sale_rights_type NON_EXCLUSIVE_LICENSE.
-- 7. AI action payload hash MUST be canonical JSON (consistent serializer and version).
-- 8. Only user session of the exact actor can APPROVE; service/agent cannot approve itself.
-- 9. Raw source files not available via public listing serializers or public object URLs.
-- 10. Audit events should be append-only; do not write secrets / personal info into logs.
-- 11. Need anti-spam/rate limit, DB backups, schema migrations, rollback tests.
-- 12. Real transfers are NOT implemented. transactions.is_demo CHECK is deliberate for MVP.
