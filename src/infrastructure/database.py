import asyncpg
import json
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
        package: dict | None = None,
        status: str = "running",
        model: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO trip_history (
                id, email, destination, start_date, end_date, flexible_dates,
                travelers_count, travelers_type, budget_range, departure_location,
                free_text, email_subject, email_body, package_json, status, model
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15, $16)
            ON CONFLICT (id) DO UPDATE SET
                email_subject = EXCLUDED.email_subject,
                email_body = EXCLUDED.email_body,
                package_json = EXCLUDED.package_json,
                status = EXCLUDED.status,
                model = EXCLUDED.model
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
            json.dumps(package) if package is not None else None,
            status,
            model,
        )

    async def update_status(self, trip_id: str, status: str) -> None:
        await self._pool.execute(
            "UPDATE trip_history SET status = $2 WHERE id = $1",
            UUID(trip_id),
            status,
        )

    async def save_feedback(self, trip_id: str, rating: int, comment: str | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO feedback (trip_id, rating, comment)
            VALUES ($1, $2, $3)
            ON CONFLICT (trip_id) DO UPDATE SET
                rating = EXCLUDED.rating,
                comment = EXCLUDED.comment
            """,
            UUID(trip_id),
            rating,
            comment,
        )

    async def is_whitelisted(self, email: str) -> bool:
        return await self._pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM email_whitelist WHERE email = $1)",
            email.lower(),
        )

    async def get_trip_history(self, trip_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, status, email_subject, email_body, package_json, timestamp, model
            FROM trip_history WHERE id = $1
            """,
            UUID(trip_id),
        )
        if row is None:
            return None
        return dict(row)