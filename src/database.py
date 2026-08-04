import asyncpg


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
            trip_id, email, destination, start_date, end_date, flexible_dates,
            travelers_count, travelers_type, budget_range, departure_location,
            free_text, email_subject, email_body,
        )

    async def save_feedback(self, trip_id: str, email: str, rating: int, note: str | None) -> None:
        await self._pool.execute(
            "INSERT INTO feedback (trip_id, email, rating, note) VALUES ($1, $2, $3, $4)",
            trip_id, email, rating, note,
        )