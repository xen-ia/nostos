import pytest
from pydantic import ValidationError

from src.core.schemas import TripCreateRequest


def test_valid_payload():
    trip = TripCreateRequest(
        email="test@example.com",
        destination="Tokyo",
        start_date="2026-09-01",
        end_date="2026-09-10",
        travelers_count=2,
        travelers_type="coppia",
    )
    assert trip.travelers_count == 2


def test_invalid_email():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="not-an-email")


def test_travelers_count_zero_rejected():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="a@b.com", travelers_count=0)


def test_travelers_count_over_cap_rejected():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="a@b.com", travelers_count=21)


def test_invalid_travelers_type_rejected():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="a@b.com", travelers_type="gruppone")


def test_invalid_date_rejected():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="a@b.com", start_date="01/09/2026")


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        TripCreateRequest(
            email="a@b.com",
            start_date="2026-09-10",
            end_date="2026-09-01",
        )


def test_end_equal_start_accepted():
    trip = TripCreateRequest(
        email="a@b.com",
        start_date="2026-09-10",
        end_date="2026-09-10",
    )
    assert trip.end_date == trip.start_date


def test_free_text_capped():
    with pytest.raises(ValidationError):
        TripCreateRequest(email="a@b.com", free_text="x" * 5001)


def test_nullable_fields_default_none():
    trip = TripCreateRequest(email="a@b.com")
    assert trip.destination is None
    assert trip.start_date is None
    assert trip.free_text == ""
