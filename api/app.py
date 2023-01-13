import uvicorn
from beanie import init_beanie
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from redis import asyncio as aioredis

from api.config import settings
from api.config.models import CollectionLog, TaskLog, ReportLog
from api.routes.task import router as bqat_task
from api.routes.scan import router as bqat_scan

app = FastAPI()


@app.on_event("startup")
async def startup_db_client():
    try:
        app.mongodb_client = AsyncIOMotorClient(settings.MGO_URL)
        app.scan = app.mongodb_client[settings.SCAN_DB]
        app.log = app.mongodb_client[settings.LOG_DB]
        if await app.mongodb_client.server_info():
            print(f"Connect to MongoDB (scan): {app.scan.name}")
        await init_beanie(
            database=app.log,
            document_models=[TaskLog, CollectionLog, ReportLog]
        )
        print(f"Connect to MongoDB (log): {app.log.name}")
    except Exception as e:
        print(f"Failed to connect MongoDB: {str(e)}")

    try:
        app.queue = aioredis.from_url(
            url=settings.RDS_URL,
            db=settings.QUEUE_DB,
            decode_responses=True
        )
        if await app.queue.info():
            print(f"Connect to Redis (queue): {settings.QUEUE_DB}")
    except Exception as e:
        print(f"Failed to connect Redis: {str(e)}")


@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()
    app.queue.close()


app.include_router(bqat_scan, tags=["scan"], prefix="/scan")
app.include_router(bqat_task, tags=["task"], prefix="/task")


def create_app():
    uvicorn.run(
        "api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG_MODE,
    )


# if __name__ == "__main__":
#     create_app()
