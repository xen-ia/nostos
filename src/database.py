import asyncpg
from datetime import date
from uuid import UUID


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_trip_history(
        self,
        trip_id: str,
        email: str,
        destination: str | None,
        start_date: str | None,
        end_date: str | None,
        flexible_dates: bool,
        travelers_count: int,
        travelers_type: str | None,
        budget_range: str | None,
        departure_location: str | None,
        free_text: str,
        email_subject: str,
        email_body: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO trip_history (
                id, email, destination, start_date, end_date, flexible_dates,
                travelers_count, travelers_type, budget_range, departure_location,
                free_text, email_subject, email_body
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            UUID(trip_id),
            email,
            destination,
            date.fromisoformat(start_date) if start_date else None,
            date.fromisoformat(end_date) if end_date else None,
            flexible_dates,
            travelers_count,
            travelers_type,
            budget_range,
            departure_location,
            free_text,
            email_subject,
            email_body,
        )