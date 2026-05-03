from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db
from app.services.scheduler import start_scheduler
from app.api import webhooks, trips, drivers, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield


app = FastAPI(title="WhatsApp Dispatch Agent", lifespan=lifespan)

app.include_router(webhooks.router)
app.include_router(trips.router)
app.include_router(drivers.router)
app.include_router(dashboard.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def serve_dashboard():
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
