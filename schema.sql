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
    trip_dossier JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT,
    version TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    send_datetime TIMESTAMPTZ,
    error_message TEXT,
    duration_seconds REAL
);

COMMENT ON COLUMN trip_history.id IS 'Unique trip identifier';
COMMENT ON COLUMN trip_history.email IS 'Recipient email address';
COMMENT ON COLUMN trip_history.destination IS 'Destination as entered by user (region or specific place)';
COMMENT ON COLUMN trip_history.start_date IS 'Trip start date';
COMMENT ON COLUMN trip_history.end_date IS 'Trip end date';
COMMENT ON COLUMN trip_history.flexible_dates IS 'Whether dates are indicative (true) or hard constraints (false)';
COMMENT ON COLUMN trip_history.travelers_count IS 'Number of travelers';
COMMENT ON COLUMN trip_history.travelers_type IS 'Traveler type (e.g., coppia, famiglia, solo)';
COMMENT ON COLUMN trip_history.departure_location IS 'Departure country/region as entered by user';
COMMENT ON COLUMN trip_history.free_text IS 'Free-text preferences and constraints from user';
COMMENT ON COLUMN trip_history.email_subject IS 'Generated email subject line';
COMMENT ON COLUMN trip_history.email_body IS 'Generated email body (HTML/text)';
COMMENT ON COLUMN trip_history.trip_dossier IS 'Full research dossier: geo resolved destinations, SerpAPI corpus (maps/places/flights), curated selections, intent, tool_calls log';
COMMENT ON COLUMN trip_history.status IS 'Trip processing status: pending, running, done, failed';
COMMENT ON COLUMN trip_history.model IS 'LLM model used for this trip';
COMMENT ON COLUMN trip_history.version IS 'Application version that processed this trip';
COMMENT ON COLUMN trip_history.processed_at IS 'Timestamp when trip processing completed';
COMMENT ON COLUMN trip_history.send_datetime IS 'Timestamp when email was sent';
COMMENT ON COLUMN trip_history.error_message IS 'Error message if trip failed';
COMMENT ON COLUMN trip_history.duration_seconds IS 'Total processing duration in seconds';

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

-- Rename package_json to trip_dossier for clarity (idempotent).
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trip_history' AND column_name = 'package_json'
    ) THEN
        ALTER TABLE trip_history RENAME COLUMN package_json TO trip_dossier;
    END IF;
END $$;

-- Display timestamps in Italian local time; storage stays UTC (TIMESTAMPTZ).
ALTER DATABASE nostos SET timezone TO 'Europe/Rome';
