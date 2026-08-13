from arq.connections import ArqRedis

from src.infrastructure.worker import QUEUE_NAME


async def enqueue_trip(arq: ArqRedis, trip_id: str) -> None:
    await arq.enqueue_job("run_trip_job", trip_id, _queue_name=QUEUE_NAME)
