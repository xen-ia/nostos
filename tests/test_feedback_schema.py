"""V2: the dead feedback.note column is gone from schema.sql.

The column was never written (save_feedback writes only trip_id/rating/comment),
so CREATE TABLE must not declare it and an idempotent DROP must migrate prod.
"""

import re

SCHEMA = "schema.sql"


def _schema() -> str:
    with open(SCHEMA, encoding="utf-8") as fh:
        return fh.read()


def test_feedback_create_has_no_note_column():
    src = _schema()
    match = re.search(r"CREATE TABLE IF NOT EXISTS feedback \((.*?)\);", src, re.DOTALL)
    assert match is not None, "CREATE TABLE feedback not found in schema.sql"
    columns = [c.strip().split()[0] for c in match.group(1).split(",")]
    assert "note" not in columns
    assert {"id", "trip_id", "rating", "comment", "created_at"} <= set(columns)


def test_feedback_note_drop_is_idempotent():
    src = _schema()
    assert "ALTER TABLE feedback DROP COLUMN IF EXISTS note;" in src
