CREATE TABLE IF NOT EXISTS trip_history (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    destination TEXT,
    start_date DATE,
    end_date DATE,
    flexible_dates BOOLEAN NOT NULL DEFAULT FALSE,
    travelers_count INTEGER NOT NULL,
    travelers_type TEXT,
    departure_location TEXT,
    free_text TEXT NOT NULL DEFAULT '',
    email_subject TEXT,
    email_body TEXT,
    package_json JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT,
    version TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    send_datetime TIMESTAMPTZ,
    error_message TEXT,
    duration_seconds REAL
);

CREATE INDEX IF NOT EXISTS idx_trip_history_email ON trip_history (email);

CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id UUID NOT NULL REFERENCES trip_history (id),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    note TEXT,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_trip_id ON feedback (trip_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_trip_id ON feedback (trip_id);

-- Upgrade existing databases (ADR-004 feedback endpoint): nullable email, comment column,
-- unique trip_id so a trip has at most one feedback (upsert target).
ALTER TABLE feedback ALTER COLUMN email DROP NOT NULL;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS comment TEXT;

CREATE TABLE IF NOT EXISTS email_whitelist (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Upgrade existing databases to the durable status column (ADR-002).
-- The column above is part of CREATE TABLE for fresh installs; this is a no-op if present.
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';

-- Upgrade existing databases: record which LLM model produced the trip.
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS model TEXT;

-- Upgrade existing databases: created_at -> timestamp -> datetime -> processed_at.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trip_history' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE trip_history RENAME COLUMN created_at TO processed_at;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trip_history' AND column_name = 'timestamp'
    ) THEN
        ALTER TABLE trip_history RENAME COLUMN timestamp TO processed_at;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trip_history' AND column_name = 'datetime'
    ) THEN
        ALTER TABLE trip_history RENAME COLUMN datetime TO processed_at;
    END IF;
END $$;

-- Upgrade existing databases: record which nostos version produced the trip.
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS version TEXT;

-- Upgrade existing databases: email send time (NULL until actually sent), failure reason
-- and pipeline duration (seconds).
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS send_datetime TIMESTAMPTZ;
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS duration_seconds REAL;

-- Upgrade existing databases: flexible_dates restored with real semantics
-- (ADR-009: absent dates => period planning; present + false => hard
-- constraint; present + true => indicative, the system may probe shifts).
ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS flexible_dates BOOLEAN NOT NULL DEFAULT FALSE;

-- Upgrade existing databases: budget_range removed (superseded by free-text budget_amount).
ALTER TABLE trip_history DROP COLUMN IF EXISTS budget_range;

-- Display timestamps in Italian local time; storage stays UTC (TIMESTAMPTZ).
ALTER DATABASE nostos SET timezone TO 'Europe/Rome';
