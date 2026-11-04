"""Baseline: schemas, least-privilege roles, source tables, PII-free analytics views, app tables, audit log.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-04
"""

import os

from alembic import op
from sqlalchemy.util import await_only

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _script(sql: str) -> None:
    """Run a multi-statement script via the simple-query protocol (asyncpg rejects it as one prepared stmt)."""
    raw = op.get_bind().connection.driver_connection
    await_only(raw.execute(sql))  # same connection, same transaction as Alembic


def _password(env: str, default: str) -> str:
    return os.environ.get(env, default).replace("'", "''")


SOURCE = """
CREATE TABLE source.regions (
    id SERIAL PRIMARY KEY,
    district TEXT NOT NULL,
    city TEXT NOT NULL
);
CREATE TABLE source.property_types (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    commission_rate NUMERIC(4, 3) NOT NULL
);
CREATE TABLE source.agents (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    hired_on DATE NOT NULL,
    region_id INT NOT NULL REFERENCES source.regions(id)
);
CREATE TABLE source.customers (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT,
    city TEXT NOT NULL,
    source TEXT NOT NULL,
    created_on DATE NOT NULL
);
CREATE TABLE source.properties (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    type_id INT NOT NULL REFERENCES source.property_types(id),
    region_id INT NOT NULL REFERENCES source.regions(id),
    project_name TEXT NOT NULL,
    area_m2 NUMERIC(8, 1) NOT NULL,
    bedrooms INT,
    list_price NUMERIC(16, 0) NOT NULL,
    listed_on DATE NOT NULL,
    agent_id INT NOT NULL REFERENCES source.agents(id)
);
CREATE TABLE source.transactions (
    id SERIAL PRIMARY KEY,
    property_id INT NOT NULL REFERENCES source.properties(id),
    customer_id INT NOT NULL REFERENCES source.customers(id),
    agent_id INT NOT NULL REFERENCES source.agents(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'deposited', 'completed', 'cancelled')),
    sale_price NUMERIC(16, 0) NOT NULL,
    commission NUMERIC(14, 0) NOT NULL,
    created_on DATE NOT NULL,
    completed_on DATE,
    CHECK ((status = 'completed') = (completed_on IS NOT NULL))
);
CREATE INDEX ix_transactions_completed_on ON source.transactions (completed_on);
CREATE INDEX ix_transactions_property ON source.transactions (property_id);
CREATE TABLE source.sales_targets (
    agent_id INT NOT NULL REFERENCES source.agents(id),
    year INT NOT NULL,
    month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    target_revenue NUMERIC(16, 0) NOT NULL,
    PRIMARY KEY (agent_id, year, month)
);
"""

ANALYTICS = """
CREATE VIEW analytics.v_transactions AS
SELECT
    t.id AS transaction_id,
    p.code AS property_code,
    pt.name AS property_type,
    p.project_name,
    r.district,
    r.city,
    a.id AS agent_id,
    a.full_name AS agent_name,
    c.source AS customer_source,
    CASE t.status
        WHEN 'completed' THEN 'Hoàn tất'
        WHEN 'deposited' THEN 'Đặt cọc'
        WHEN 'pending' THEN 'Đang xử lý'
        ELSE 'Đã hủy'
    END AS status,
    t.sale_price,
    t.commission,
    t.created_on AS created_date,
    t.completed_on AS completed_date
FROM source.transactions t
JOIN source.properties p ON p.id = t.property_id
JOIN source.property_types pt ON pt.id = p.type_id
JOIN source.regions r ON r.id = p.region_id
JOIN source.agents a ON a.id = t.agent_id
JOIN source.customers c ON c.id = t.customer_id;

CREATE VIEW analytics.v_properties AS
SELECT
    p.code AS property_code,
    pt.name AS property_type,
    p.project_name,
    r.district,
    r.city,
    p.area_m2,
    p.bedrooms,
    p.list_price,
    ROUND(p.list_price / NULLIF(p.area_m2, 0)) AS price_per_m2,
    p.listed_on AS listed_date,
    NOT EXISTS (
        SELECT 1 FROM source.transactions t
        WHERE t.property_id = p.id AND t.status IN ('pending', 'deposited', 'completed')
    ) AS is_available,
    a.full_name AS agent_name
FROM source.properties p
JOIN source.property_types pt ON pt.id = p.type_id
JOIN source.regions r ON r.id = p.region_id
JOIN source.agents a ON a.id = p.agent_id;

-- No name, phone or e-mail: customers are only visible as anonymous ids.
CREATE VIEW analytics.v_customers AS
SELECT
    c.id AS customer_id,
    c.city,
    c.source AS customer_source,
    c.created_on AS created_date,
    COUNT(t.id) FILTER (WHERE t.status = 'completed')::int AS completed_purchases,
    COALESCE(SUM(t.sale_price) FILTER (WHERE t.status = 'completed'), 0) AS total_spent
FROM source.customers c
LEFT JOIN source.transactions t ON t.customer_id = c.id
GROUP BY c.id;

CREATE VIEW analytics.v_agent_monthly AS
WITH done AS (
    SELECT agent_id,
           EXTRACT(YEAR FROM completed_on)::int AS year,
           EXTRACT(MONTH FROM completed_on)::int AS month,
           SUM(sale_price) AS revenue,
           SUM(commission) AS commission,
           COUNT(*)::int AS completed_deals
    FROM source.transactions
    WHERE status = 'completed'
    GROUP BY 1, 2, 3
)
SELECT
    a.id AS agent_id,
    a.full_name AS agent_name,
    r.district,
    r.city,
    st.year,
    st.month,
    COALESCE(d.revenue, 0) AS revenue,
    COALESCE(d.commission, 0) AS commission,
    COALESCE(d.completed_deals, 0) AS completed_deals,
    st.target_revenue
FROM source.sales_targets st
JOIN source.agents a ON a.id = st.agent_id
JOIN source.regions r ON r.id = a.region_id
LEFT JOIN done d ON d.agent_id = st.agent_id AND d.year = st.year AND d.month = st.month;
"""

APP = """
CREATE TABLE app.users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(10) NOT NULL DEFAULT 'user' CONSTRAINT ck_users_role CHECK (role IN ('user', 'admin')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE app.entitlements (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    dataset_code VARCHAR(64) NOT NULL,
    granted_by INT REFERENCES app.users(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT uq_entitlements_user_id UNIQUE (user_id, dataset_code)
);
CREATE TABLE app.access_requests (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    dataset_code VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CONSTRAINT ck_access_requests_status CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    reviewer_id INT REFERENCES app.users(id),
    review_comment TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ
);
CREATE INDEX ix_access_requests_user_id ON app.access_requests (user_id);
CREATE INDEX ix_access_requests_status ON app.access_requests (status);
CREATE TABLE app.conversations (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_conversations_user_id ON app.conversations (user_id);
CREATE TABLE app.query_runs (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    conversation_id INT NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    standalone_question TEXT,
    dataset_code VARCHAR(64),
    status VARCHAR(20) NOT NULL CONSTRAINT ck_query_runs_status CHECK (status IN (
        'blocked', 'answered', 'clarification', 'access_required', 'rejected', 'awaiting_approval',
        'running', 'succeeded', 'failed', 'cancelled', 'superseded', 'expired')),
    sql TEXT,
    sql_hash VARCHAR(64),
    interpretation TEXT,
    assumptions JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    sql_attempts SMALLINT NOT NULL DEFAULT 0,
    risk_level VARCHAR(10),
    edited BOOLEAN NOT NULL DEFAULT false,
    auto_executed BOOLEAN NOT NULL DEFAULT false,
    expires_at TIMESTAMPTZ,
    columns JSONB,
    rows JSONB,
    row_count INT,
    truncated BOOLEAN NOT NULL DEFAULT false,
    chart JSONB,
    explanation JSONB,
    explanation_grounded BOOLEAN,
    error_message TEXT,
    trace_id VARCHAR(64),
    prompt_version VARCHAR(20),
    llm_model VARCHAR(80),
    llm_route VARCHAR(20),
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    planning_ms INT,
    execution_ms INT,
    explain_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX ix_query_runs_user_id ON app.query_runs (user_id);
CREATE INDEX ix_query_runs_conversation_id ON app.query_runs (conversation_id);
CREATE INDEX ix_query_runs_status ON app.query_runs (status);
CREATE INDEX ix_query_runs_created_at ON app.query_runs (created_at);
CREATE TABLE app.messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
    role VARCHAR(10) NOT NULL CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    query_run_id INT REFERENCES app.query_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_messages_conversation_id ON app.messages (conversation_id);
CREATE TABLE app.feedback (
    id SERIAL PRIMARY KEY,
    query_run_id INT NOT NULL REFERENCES app.query_runs(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    rating SMALLINT NOT NULL CONSTRAINT ck_feedback_rating CHECK (rating IN (-1, 1)),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_feedback_query_run_id UNIQUE (query_run_id, user_id)
);

-- Append-only audit trail: no FK cascade into it, and a trigger rejects UPDATE/DELETE for everyone.
CREATE TABLE app.audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor_id INT REFERENCES app.users(id),
    action VARCHAR(40) NOT NULL,
    entity VARCHAR(30) NOT NULL,
    entity_id INT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_events_action ON app.audit_events (action);
CREATE FUNCTION app.reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'app.audit_events is append-only';
END $$;
CREATE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE ON app.audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_audit_mutation();
"""


def upgrade() -> None:
    app_pw = _password("APP_BACKEND_PASSWORD", "app_backend")
    reader_pw = _password("ANALYTICS_READER_PASSWORD", "analytics_reader")
    _script(
        "CREATE SCHEMA IF NOT EXISTS source; CREATE SCHEMA IF NOT EXISTS analytics; CREATE SCHEMA IF NOT EXISTS app;"
    )
    _script(SOURCE)
    _script(ANALYTICS)
    _script(APP)
    _script(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
                CREATE ROLE app_backend LOGIN PASSWORD '{app_pw}';
            ELSE
                ALTER ROLE app_backend WITH LOGIN PASSWORD '{app_pw}';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
                CREATE ROLE analytics_reader LOGIN PASSWORD '{reader_pw}';
            ELSE
                ALTER ROLE analytics_reader WITH LOGIN PASSWORD '{reader_pw}';
            END IF;
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_backend, analytics_reader', current_database());
        END $$;
        """
    )
    _script(
        """
        REVOKE ALL ON SCHEMA source FROM PUBLIC;
        REVOKE ALL ON ALL TABLES IN SCHEMA source FROM PUBLIC;

        -- analytics_reader: SELECT on the analytics views only. Views run with the owner's rights,
        -- so the role needs no privilege on `source`.
        GRANT USAGE ON SCHEMA analytics TO analytics_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analytics_reader;
        ALTER ROLE analytics_reader SET default_transaction_read_only = on;
        ALTER ROLE analytics_reader SET statement_timeout = '15s';
        ALTER ROLE analytics_reader SET search_path = analytics;

        -- app_backend: product state only; audit log is insert/select only.
        GRANT USAGE ON SCHEMA app TO app_backend;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_backend;
        REVOKE UPDATE, DELETE, TRUNCATE ON app.audit_events FROM app_backend;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO app_backend;
        ALTER ROLE app_backend SET search_path = app;
        """
    )


def downgrade() -> None:
    _script(
        "DROP SCHEMA IF EXISTS analytics CASCADE; DROP SCHEMA IF EXISTS app CASCADE; DROP SCHEMA IF EXISTS source CASCADE;"
    )
