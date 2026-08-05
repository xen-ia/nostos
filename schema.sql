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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trip_history_email ON trip_history (email);

CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id UUID NOT NULL REFERENCES trip_history (id),
    email TEXT NOT NULL,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_trip_id ON feedback (trip_id);