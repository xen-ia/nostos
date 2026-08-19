CREATE TABLE IF NOT EXISTS trip_history (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    destination TEXT,
    start_date DATE,
    end_date DATE,
    flexible_dates BOOLEAN NOT NULL DEFAULT FALSE,
    travelers_count INTEGER NOT NULL,
    travelers_type TEXT,
    budget_range TEXT,
    departure_location TEXT,
    free_text TEXT NOT NULL DEFAULT '',
    email_subject TEXT,
    email_body TEXT,
    package_json JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
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

-- Upgrade existing databases: created_at was renamed to timestamp.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'trip_history' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE trip_history RENAME COLUMN created_at TO timestamp;
    END IF;
END $$;
