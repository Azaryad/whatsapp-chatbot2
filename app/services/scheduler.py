"""APScheduler wrapper for offer timeout jobs."""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()})

# In-memory store: offer_id → (ranked, tried_driver_ids)
_offer_state: dict[int, tuple[list[dict], list[int]]] = {}


def start_scheduler():
    scheduler.start()


def schedule_offer_timeout(
    offer_id: int,
    expires_at: datetime,
    trip_id: int,
    ranked: list[dict],
    tried_driver_ids: list[int],
) -> None:
    _offer_state[offer_id] = (ranked, tried_driver_ids)

    async def _run():
        from app.services.dispatch import handle_offer_timeout
        await handle_offer_timeout(offer_id, trip_id, ranked, tried_driver_ids)
        _offer_state.pop(offer_id, None)

    scheduler.add_job(
        _run,
        trigger="date",
        run_date=expires_at,
        id=f"offer_timeout_{offer_id}",
        replace_existing=True,
        misfire_grace_time=300,
    )


def cancel_offer_timeout(offer_id: int) -> None:
    job_id = f"offer_timeout_{offer_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    _offer_state.pop(offer_id, None)


def get_ranked_list(offer_id: int) -> tuple[list[dict], list[int]]:
    return _offer_state.get(offer_id, ([], []))
