import re

from src.infrastructure.database import SAVE_TRIP_HISTORY_SQL

EXPECTED_COLUMNS = [
    "id",
    "email",
    "destination",
    "start_date",
    "end_date",
    "travelers_count",
    "travelers_type",
    "budget_range",
    "departure_location",
    "free_text",
    "email_subject",
    "email_body",
    "package_json",
    "status",
    "model",
    "version",
]


def _columns() -> list[str]:
    match = re.search(r"INSERT INTO trip_history \((.*?)\)", SAVE_TRIP_HISTORY_SQL, re.DOTALL)
    assert match is not None, "SAVE_TRIP_HISTORY_SQL must contain an INSERT INTO trip_history"
    return [c.strip() for c in match.group(1).split(",")]


def _placeholders() -> list[str]:
    values = re.search(r"VALUES\s*\((.*?)\)\s*\n\s*ON CONFLICT", SAVE_TRIP_HISTORY_SQL, re.DOTALL)
    assert values is not None, "SAVE_TRIP_HISTORY_SQL must contain a VALUES clause before ON CONFLICT"
    return [p.strip() for p in values.group(1).split(",")]


def test_insert_columns_match_expected_order():
    assert _columns() == EXPECTED_COLUMNS


def test_placeholder_count_matches_column_count():
    placeholders = _placeholders()
    assert len(placeholders) == len(EXPECTED_COLUMNS)


def test_placeholders_are_sequential_from_one():
    placeholders = _placeholders()
    for i, ph in enumerate(placeholders, start=1):
        assert re.fullmatch(rf"\${i}(?:::jsonb)?", ph), f"position {i}: unexpected placeholder {ph!r}"


def test_jsonb_cast_on_package_json_position():
    placeholders = _placeholders()
    package_pos = EXPECTED_COLUMNS.index("package_json")
    for i, (col, ph) in enumerate(zip(EXPECTED_COLUMNS, placeholders), start=1):
        if col == "package_json":
            assert ph == f"${i}::jsonb"
        else:
            assert "::jsonb" not in ph, f"unexpected ::jsonb cast on column {col}"
