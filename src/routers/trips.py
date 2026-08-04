from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.apis.email import EmailSender
from src.apis.llm import LLMClient
from src.dependencies import get_email_sender, get_llm_client, get_trip_store
from src.pipeline import TripOrchestrator
from src.trip_store import TripCreateRequest, TripNotFoundError, TripResponse, TripStore

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripResponse)
async def create_trip(
    payload: TripCreateRequest,
    background_tasks: BackgroundTasks,
    store: TripStore = Depends(get_trip_store),
    llm_client: LLMClient = Depends(get_llm_client),
    email_sender: EmailSender = Depends(get_email_sender),
):
    trip = await store.create(payload)

    orchestrator = TripOrchestrator(
        store=store,
        llm_client=llm_client,
        email_sender=email_sender,
        trip_id=trip.id,
    )
    background_tasks.add_task(orchestrator.run)

    return trip


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(trip_id: str, store: TripStore = Depends(get_trip_store)):
    try:
        return await store.get(trip_id)
    except TripNotFoundError:
        raise HTTPException(status_code=404, detail="Viaggio non trovato o scaduto")