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

-- inspect table from the pg public schema; tables: trip_history, ...
   SELECT c.column_name,
          c.data_type,
          -- TRUE se PRIMARY KEY reale
          (pk.column_name IS NOT NULL) AS primary_key,
          -- Commento colonna
          pgd.description
     FROM information_schema.columns c
-- PRIMARY KEY
LEFT JOIN (
    SELECT kcu.table_schema,
           kcu.table_name,
           kcu.column_name
      FROM information_schema.table_constraints tc
      JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
       AND tc.table_schema = kcu.table_schema
     WHERE tc.constraint_type = 'PRIMARY KEY'
) pk
         ON pk.table_schema = c.table_schema
         AND pk.table_name   = c.table_name
         AND pk.column_name  = c.column_name
-- COLUMN COMMENTS
LEFT JOIN pg_catalog.pg_statio_all_tables st
       ON st.schemaname = c.table_schema
      AND st.relname   = c.table_name
LEFT JOIN pg_catalog.pg_description pgd
       ON pgd.objoid   = st.relid
      AND pgd.objsubid = c.ordinal_position
    WHERE c.table_schema = 'public'
      AND c.table_name   = 'trip_history'
 ORDER BY c.ordinal_position
;
